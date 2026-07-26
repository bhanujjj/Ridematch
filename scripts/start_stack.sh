#!/usr/bin/env bash
# RideMatch — bring the full stack up and serve the match API.
# Usage:  bash scripts/start_stack.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs reports

# --- MinIO / S3 credentials (used by Feast + pyarrow) ---
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export AWS_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:9000
export AWS_S3_ENDPOINT=http://localhost:9000
export AWS_S3_ADDRESSING_STYLE=path
export ARROW_S3_USE_PATH_STYLE=1
export AWS_S3_USE_HTTPS=0
export MLFLOW_TRACKING_URI=http://localhost:5050

# Prefer the existing venv if present
if [ -d "$ROOT/.mlflow-venv" ]; then
  # shellcheck disable=SC1091
  source "$ROOT/.mlflow-venv/bin/activate"
fi
PY="$(command -v python3 || command -v python)"
echo "python: $PY"

echo "==> 1/7  docker compose up (waiting on healthchecks)"
# --wait blocks until every service with a healthcheck reports healthy, so we
# no longer guess with `sleep 30`. kafka-init/minio-init create the topic and
# buckets and then exit 0.
( cd infra && (docker compose up -d --wait || docker-compose up -d) )
docker ps --format 'table {{.Names}}\t{{.Status}}'

echo "==> 2/7  verifying kafka topic + minio buckets"
docker exec kafka kafka-topics --bootstrap-server localhost:29092 --list | sed 's/^/    topic: /'
docker exec redis redis-cli ping | sed 's/^/    redis: /'

echo "==> 3/7  starting event generator (background)"
pkill -f "python.*generator.py" 2>/dev/null || true
( cd data_sim && nohup "$PY" generator.py > "$ROOT/logs/generator.log" 2>&1 & )
sleep 15   # let some events land in Kafka

echo "==> 4/7  ETL: Kafka -> parquet -> MinIO (3 batches)"
for b in 1 2 3; do
  ( cd prefect/flows && "$PY" etl_flow.py ) 2>&1 | tail -5
  sleep 8
done

echo "==> 5/7  feast apply + materialize to Redis"
( cd feature_repo && feast apply && "$PY" materialize_features.py ) || {
  echo "    materialize failed -> falling back to direct Redis populate"
  ( cd feature_repo && "$PY" populate_online_store.py )
}
echo "    redis keys: $(docker exec redis redis-cli dbsize)"

echo "==> 6/7  train ranking model"
( cd src/models && "$PY" train_ranking_model.py ) 2>&1 | tail -15

echo "==> 7/7  serving API on :8000"
pkill -f "uvicorn src.match_api.main" 2>/dev/null || true
# Threadpool-backed sync endpoint: more workers => real parallelism across cores.
WORKERS="${API_WORKERS:-4}"
nohup "$PY" -m uvicorn src.match_api.main:app --host 0.0.0.0 --port 8000 \
  --workers "$WORKERS" > "$ROOT/logs/api.log" 2>&1 &
ready=0
for i in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/ready || true)
  if [ "$code" = "200" ]; then echo "    API ready (after ${i}s, $WORKERS workers)"; ready=1; break; fi
  sleep 1
done
if [ "$ready" != "1" ]; then
  echo "    API not ready. /ready says:"
  curl -s http://localhost:8000/ready || true
  echo; echo "    last 30 lines of logs/api.log:"; tail -30 "$ROOT/logs/api.log"
fi

cat <<EOF

Stack is up.
  API        http://localhost:8000/docs
  MinIO      http://localhost:9001   (minioadmin/minioadmin)
  MLflow     http://localhost:5050
  Prefect    http://localhost:4200
  Prometheus http://localhost:9090
  Grafana    http://localhost:3000   (admin/admin)

Measure latency:
  python scripts/bench_latency.py -n 1000 -c 20

Logs: logs/api.log, logs/generator.log
EOF
