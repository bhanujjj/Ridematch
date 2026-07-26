# RideMatch — Run & Debug Handoff

Context for whoever (or whatever) runs this next. The code was just refactored
but **has never been executed end-to-end against live infrastructure**. Every
Python file compiles and 12/12 unit tests pass, but nothing has touched a real
Kafka broker, Redis, or MinIO since the changes. Assume the first run will
surface something.

---

## Stack

| Layer | Tech | Where |
|---|---|---|
| Streaming | Kafka 7.6.1 (KRaft, no Zookeeper) | `localhost:9092` (host), `kafka:29092` (in-network) |
| Object store | MinIO | `localhost:9000`, console `:9001`, `minioadmin/minioadmin` |
| Online store | Redis 7.2 | `localhost:6379` |
| Feature store | Feast 0.40.1 | `feature_repo/` |
| Model registry | MLflow 2.13 + Postgres, artifacts in MinIO | `localhost:5050` |
| Orchestration | Prefect 2.19 | `localhost:4200` |
| Serving | FastAPI + uvicorn | `localhost:8000` |
| Observability | Prometheus + Grafana | `:9090`, `:3000` (`admin/admin`) |

---

## Run it

### 0. Prerequisites
Docker Desktop must be running. Confirm with `docker info`.

### 1. Wipe old volumes — REQUIRED
```bash
cd ~/Desktop/Projects/RideMatch
docker compose -f infra/docker-compose.yml down -v
```
Kafka switched from Zookeeper (`wurstmeister/kafka`) to KRaft
(`confluentinc/cp-kafka`). **The new broker will not start against old
Zookeeper-era volumes.** If you skip this you get a cryptic cluster-ID
mismatch in the kafka logs.

### 2. Install deps
```bash
source .mlflow-venv/bin/activate
pip install -r requirements.txt
```
`fastapi`, `uvicorn[standard]`, `prometheus-client`, `httpx` were added — the
API imported them but they were never declared.

### 3. One-shot startup
```bash
bash scripts/start_stack.sh
```
Does all seven steps: compose up (waits on healthchecks), verifies topic +
buckets, starts the generator, runs 3 ETL batches, `feast apply` +
materialize, trains the model, serves the API, polls `/ready`.

If it fails, run the steps manually — see "Manual sequence" below.

### 4. Measure latency
```bash
python scripts/bench_latency.py -n 1000 -c 20
```
Prints p50/p90/p95/p99 + throughput, writes `reports/latency.json`.
Flags: `--url`, `-n/--requests`, `-c/--concurrency`, `--top-k`, `--warmup`.

### 5. Tests
```bash
python -m pytest tests/ -q
```
`tests/test_training_logic.py` stubs feast/mlflow, so it needs no infra.

---

## Manual sequence (if start_stack.sh fails)

```bash
cd infra && docker compose up -d --wait && cd ..
docker ps                                    # all should be healthy

cd data_sim   && python generator.py &       # continuous; leave running
cd prefect/flows && python etl_flow.py       # repeat 3x, ~8s apart
cd feature_repo  && feast apply && python materialize_features.py
docker exec redis redis-cli dbsize           # MUST be > 0
cd src/models && python train_ranking_model.py
uvicorn src.match_api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## Known failure modes

**`docker exec redis redis-cli dbsize` returns 0**
Online store is empty, so `/match` returns `{"matches": []}` and the benchmark
measures nothing useful. `materialize_features.py` has a known Feast timestamp
bug on older parquet files; it auto-falls back to `populate_online_store.py`.
If both fail, clear stale data and re-ingest:
```bash
docker exec minio mc rm --recursive --force local/ridematch-raw/
```

**ETL prints "Consumed 0 messages"**
Consumer group already read them. Either wait for the generator to produce
more, or reset:
```bash
docker exec kafka kafka-consumer-groups --bootstrap-server localhost:29092 \
  --delete --group ridematch-consumer
```
Note the port is **29092** for in-container commands, not 9092.

**`/ready` returns 503**
Response body names which resource failed (`feature_store` / `model`).
Startup is intentionally non-fatal now, so the process stays up and
debuggable. Check `logs/api.log`.

**MLflow container restarting**
It `pip install`s `psycopg2-binary` + `boto3` at boot, so first start takes
~60s. `start_period` is set to 60s. Only worry if it's still cycling after
that.

**Feast `s3://` read errors**
PyArrow needs the MinIO env vars set *before* `feast` is imported. That's what
`feature_repo/minio_config.py` does (it now delegates to `src/config.py`).
Any new script touching Feast must `import minio_config` first.

---

## What changed, and why it might break

Full rationale is in the code comments. The behavioural changes:

1. **`src/models/train_ranking_model.py` — label leakage removed.**
   `simulate_ride_requests` used to label the nearest driver `1` while feeding
   `distance_km` as a feature. Replaced with a stochastic logistic acceptance
   model. Expect **val AUC ≈ 0.85**, not 0.99. If you see >0.99 the tripwire
   will warn — that means leakage came back, not that things improved.

2. **`src/match_api/main.py` — `/match` is now sync `def`, not `async def`.**
   It does blocking Redis + CPU-bound sklearn work; as `async` it serialised
   every concurrent request on the event loop. Sync = FastAPI threadpool =
   real concurrency. Do not "fix" this back to async.

3. **Drift tracking vectorized.** `df.iterrows()` over 100 candidates × 3
   features per request is gone. `DriftDetector.observe_many()` added.

4. **Per-feature Prometheus histograms.** `feature_values{feature_name=...}`
   was one labelled histogram with shared buckets across features on totally
   different scales. Now three: `feature_distance_km`,
   `feature_accept_rate_7d`, `feature_avg_response_ms`.
   **Any saved Grafana panel referencing `feature_values` needs updating.**

5. **`/health` (liveness, always 200) and `/ready` (readiness, 503 until
   loaded)** added. `sys.exit()` removed from the lifespan handler.

6. **`src/config.py` is new** — all endpoints/credentials env-driven with
   localhost defaults. `etl_flow.py`, `minio_config.py`, `feature_views.py`
   now read from it. Nothing is hardcoded at a call site.

7. **ETL is at-least-once.** Kafka auto-commit disabled; offsets commit only
   after the parquet lands in MinIO. A failed batch replays instead of
   vanishing. It also writes via a temp dir rather than the CWD.

8. **`infra/docker-compose.yml` rewritten.** KRaft Kafka, all images pinned,
   healthchecks + `depends_on.condition`, `MINIO_ROOT_USER`/`_PASSWORD`
   (the old `MINIO_ACCESS_KEY` vars are silently ignored by current MinIO —
   it was running on defaults by accident), MLflow on Postgres with S3
   artifacts, `kafka-init`/`minio-init` bootstrap containers, Grafana
   datasource + dashboard auto-provisioned.

9. **`Dockerfile` added** — multi-stage, non-root, healthcheck. Not yet built
   or wired into compose.

---

## Not done

- **Feast registry is still a local file** (`feature_repo/data/registry.db`).
  Moving it to Postgres/S3 is the real production answer but requires
  rebuilding the registry.
- **The API is not in docker-compose.** The Dockerfile exists and is
  unbuilt/untested; the API currently runs on the host via uvicorn.
- **`feature_store.yaml` says `offline_store: type: file`** while reading
  `s3://` paths. It works via PyArrow but is confusing.
- **Stray artifacts in the repo**: `prefect/flows/*.parquet`,
  `events_*.parquet`, `test_events.parquet`, committed `mlruns/` and
  `infra/minio_data/`. Should be gitignored.
- Grafana dashboard JSON not re-checked against the renamed metrics (see #4).

---

## Task for Claude Code

Bring the stack up, run the pipeline end to end, and fix whatever breaks.
Success criteria, in order:

1. `docker compose -f infra/docker-compose.yml ps` — every service healthy
2. `docker exec redis redis-cli dbsize` — greater than 0
3. `curl -s localhost:8000/ready` — HTTP 200
4. `curl -sX POST localhost:8000/match -H 'Content-Type: application/json' \
   -d '{"rider_id":"r1","rider_lat":37.77,"rider_lon":-122.42,"top_k":5}'`
   — returns a non-empty `matches` array
5. `python scripts/bench_latency.py -n 1000 -c 20` — completes, reports p99
6. `python -m pytest tests/ -q` — all pass

Report the p50/p95/p99 numbers at the end.
