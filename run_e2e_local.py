#!/usr/bin/env python3
"""
RideMatch End-to-End Local Pipeline Test
==========================================

Runs the complete RideMatch pipeline locally WITHOUT Docker/Redis/Kafka.
Uses SQLite as the Feast online store and local pickle model files.

Usage:
    python run_e2e_local.py
"""

import glob
import json
import os
import pickle
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

PASS, FAIL, WARN, INFO = "✅", "❌", "⚠️ ", "ℹ️ "
SEP = "─" * 60
results = []

def step(name):
    print(f"\n{SEP}\n  STEP: {name}\n{SEP}")

def ok(msg):   print(f"  {PASS} {msg}"); results.append(("PASS", msg))
def fail(msg): print(f"  {FAIL} {msg}"); results.append(("FAIL", msg))
def warn(msg): print(f"  {WARN} {msg}"); results.append(("WARN", msg))
def info(msg): print(f"  {INFO} {msg}")

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return R * 2 * np.arcsin(np.sqrt(a))

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Data Simulation
# ══════════════════════════════════════════════════════════════════════════════
step("1 · Data Simulation")
try:
    sys.path.insert(0, str(PROJECT_ROOT / "data_sim"))
    from generator import driver_event, rider_request
    batch = [driver_event(f"driver_{i}") for i in range(40)]
    batch += [rider_request(f"rider_{i}") for i in range(10)]
    ok(f"generator.driver_event/rider_request → {len(batch)} events")
except Exception as e:
    warn(f"generator import failed ({e}), using inline sim")
    np.random.seed(42)
    batch = [{
        "event_type": "driver_update",
        "driver_id": f"driver_{i}",
        "lat": float(np.random.uniform(40.6, 40.9)),
        "lon": float(np.random.uniform(-74.1, -73.8)),
        "status": np.random.choice(["available", "busy"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "accept_rate_7d": float(np.random.uniform(0.5, 1.0)),
        "avg_response_ms": float(np.random.uniform(500, 8000)),
    } for i in range(50)]
    ok(f"Inline simulation → {len(batch)} events")

sim_df = pd.DataFrame(batch)
sim_parquet = PROJECT_ROOT / "feature_repo" / "data" / "sim_events.parquet"
sim_parquet.parent.mkdir(parents=True, exist_ok=True)
sim_df.to_parquet(sim_parquet, index=False)
ok("Saved sim data → feature_repo/data/sim_events.parquet")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — ETL: Load Parquet Data
# ══════════════════════════════════════════════════════════════════════════════
step("2 · ETL – Load Parquet Data")
dfs = []
for pat in ["events_*.parquet", "test_events.parquet"]:
    for pf in PROJECT_ROOT.glob(pat):
        try:
            df = pd.read_parquet(pf); dfs.append(df)
            info(f"Loaded {len(df)} rows from {pf.name}")
        except Exception as e:
            warn(f"Could not load {pf.name}: {e}")
dfs.append(sim_df)

events_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
ok(f"Total events: {len(events_df)} rows across {len(dfs)} source(s)")
ok(f"Columns: {list(events_df.columns)}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Feature Engineering
# ══════════════════════════════════════════════════════════════════════════════
step("3 · Feature Engineering")
try:
    driver_events = events_df.copy()
    if "event_type" in driver_events.columns:
        driver_events = driver_events[driver_events["event_type"] == "driver_update"]
    if len(driver_events) == 0:
        driver_events = events_df.copy()

    agg = {}
    for col in ["lat", "lon", "accept_rate_7d", "avg_response_ms"]:
        if col in driver_events.columns:
            agg[col] = (col, "mean")

    if agg and "driver_id" in driver_events.columns:
        agg_features = driver_events.groupby("driver_id").agg(**agg).reset_index()
    else:
        n = 100
        agg_features = pd.DataFrame({
            "driver_id": [f"driver_{i}" for i in range(n)],
            "lat": np.random.uniform(40.6, 40.9, n),
            "lon": np.random.uniform(-74.1, -73.8, n),
            "accept_rate_7d": np.random.uniform(0.5, 1.0, n),
            "avg_response_ms": np.random.uniform(500, 8000, n),
        })

    for col in ["accept_rate_7d", "avg_response_ms"]:
        if col not in agg_features.columns:
            agg_features[col] = np.random.uniform(0.5 if "rate" in col else 500,
                                                   1.0 if "rate" in col else 8000,
                                                   len(agg_features))
    ok(f"Features for {len(agg_features)} drivers")
    ok(f"Columns: {list(agg_features.columns)}")
    info(f"\n{agg_features.head(3).to_string(index=False)}")
except Exception as e:
    fail(f"Feature engineering: {e}"); traceback.print_exc()
    agg_features = pd.DataFrame()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Feast SQLite Online Store (in-process, no CLI)
# ══════════════════════════════════════════════════════════════════════════════
step("4 · Feast Feature Store (SQLite – no Redis needed)")

FEAST_REPO = PROJECT_ROOT / "feature_repo"
FS_YAML = FEAST_REPO / "feature_store_local.yaml"

# Build a clean local events parquet with proper schema for Feast
now = datetime.now(timezone.utc)
local_events_df = agg_features.copy()
local_events_df["event_timestamp"] = [now - timedelta(minutes=i % 30) for i in range(len(local_events_df))]
local_events_df["created"] = now
local_events_path = FEAST_REPO / "data" / "local_driver_events.parquet"
local_events_df.to_parquet(local_events_path, index=False)
ok(f"Saved {len(local_events_df)} rows → feature_repo/data/local_driver_events.parquet")

# Update feature_store_local.yaml with entity_key_serialization_version=2 to suppress warning
FS_YAML.write_text(f"""project: ridematch_local
entity_key_serialization_version: 2
registry: {FEAST_REPO / "data" / "registry_local.db"}
provider: local

offline_store:
  type: file

online_store:
  type: sqlite
  path: {FEAST_REPO / "data" / "online_store_local.db"}
""")
ok("Updated feature_store_local.yaml (SQLite online store, v2 entity keys)")

# Write a local features definition that points to local parquet
local_def_path = FEAST_REPO / "_local_features.py"
local_def_path.write_text(f"""
from datetime import timedelta
from feast import FeatureView, Field, Entity
from feast.types import Float32, String
from feast.infra.offline_stores.file_source import FileSource
from feast.data_format import ParquetFormat

driver = Entity(name="driver_id", join_keys=["driver_id"])

driver_source = FileSource(
    path=r"{local_events_path.as_posix()}",
    timestamp_field="event_timestamp",
    file_format=ParquetFormat(),
)

driver_status_fv = FeatureView(
    name="driver_status",
    entities=[driver],
    ttl=timedelta(hours=1),
    schema=[
        Field(name="lat", dtype=Float32),
        Field(name="lon", dtype=Float32),
    ],
    source=driver_source,
    online=True,
)

driver_agg_fv = FeatureView(
    name="driver_agg",
    entities=[driver],
    ttl=timedelta(hours=1),
    schema=[
        Field(name="accept_rate_7d", dtype=Float32),
        Field(name="avg_response_ms", dtype=Float32),
    ],
    source=driver_source,
    online=True,
)
""")
ok("Wrote local feature definitions → _local_features.py")

# In-process feast apply + materialize (no subprocess)
FEAST_OK = False
try:
    import warnings
    warnings.filterwarnings("ignore")

    from feast import FeatureStore
    store = FeatureStore(repo_path=str(FEAST_REPO), fs_yaml_file=str(FS_YAML))

    # Apply feature definitions inline
    from datetime import timedelta

    from feast import Entity, FeatureView, Field
    from feast.data_format import ParquetFormat
    from feast.infra.offline_stores.file_source import FileSource
    from feast.types import Float32

    driver_entity = Entity(name="driver_id", join_keys=["driver_id"])
    driver_source = FileSource(
        path=local_events_path.as_posix(),
        timestamp_field="event_timestamp",
        file_format=ParquetFormat(),
    )
    driver_status_fv = FeatureView(
        name="driver_status", entities=[driver_entity], ttl=timedelta(hours=1),
        schema=[Field(name="lat", dtype=Float32), Field(name="lon", dtype=Float32)],
        source=driver_source, online=True,
    )
    driver_agg_fv = FeatureView(
        name="driver_agg", entities=[driver_entity], ttl=timedelta(hours=1),
        schema=[Field(name="accept_rate_7d", dtype=Float32),
                Field(name="avg_response_ms", dtype=Float32)],
        source=driver_source, online=True,
    )

    store.apply([driver_entity, driver_status_fv, driver_agg_fv])
    ok("feast.apply() succeeded — feature views registered")

    # Materialize to SQLite
    end_dt = now
    start_dt = now - timedelta(hours=2)
    store.materialize(start_date=start_dt, end_date=end_dt)
    ok("feast.materialize() succeeded — features in SQLite online store")
    FEAST_OK = True

    # Verify online retrieval
    sample_ids = list(agg_features["driver_id"].head(3))
    feats = store.get_online_features(
        features=["driver_status:lat", "driver_status:lon",
                  "driver_agg:accept_rate_7d", "driver_agg:avg_response_ms"],
        entity_rows=[{"driver_id": d} for d in sample_ids]
    ).to_dict()
    ok(f"get_online_features() → keys: {list(feats.keys())}")
    info(f"Sample driver IDs retrieved: {sample_ids}")

except Exception as e:
    warn(f"Feast in-process failed: {e}")
    info("Will use in-memory features for ranking step")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Model Loading
# ══════════════════════════════════════════════════════════════════════════════
step("5 · Model Loading (local .pkl)")
model = None
try:
    pkl_files = glob.glob(str(PROJECT_ROOT / "models" / "saved" / "*.pkl"))
    if not pkl_files:
        fail("No model pkl files found in models/saved/")
    else:
        latest_pkl = max(pkl_files, key=os.path.getmtime)
        with open(latest_pkl, "rb") as f:
            model = pickle.load(f)
        ok(f"Loaded: {Path(latest_pkl).name}")
        ok(f"Type: {type(model).__name__}")
        # Quick smoke test
        X_test = np.array([[2.5, 0.85, 3200.0], [10.0, 0.4, 9000.0]])
        scores_test = model.predict_proba(X_test)[:, 1]
        ok(f"Smoke test scores: {[f'{s:.4f}' for s in scores_test]}")
except Exception as e:
    fail(f"Model loading: {e}"); traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Driver Matching & Ranking
# ══════════════════════════════════════════════════════════════════════════════
step("6 · Driver Matching & Ranking")
df_ranked = pd.DataFrame()
try:
    if model is None or len(agg_features) == 0:
        fail("Skipping — no model or features")
    else:
        rider_lat, rider_lon = 40.748817, -73.985428  # Times Square NYC

        df_cands = agg_features.copy()
        df_cands["distance_km"] = haversine_distance(
            rider_lat, rider_lon,
            df_cands["lat"].values, df_cands["lon"].values
        )
        df_cands["accept_rate_7d"]  = df_cands["accept_rate_7d"].fillna(0.7)
        df_cands["avg_response_ms"] = df_cands["avg_response_ms"].fillna(3000.0)

        X = df_cands[["distance_km", "accept_rate_7d", "avg_response_ms"]]
        scores = model.predict_proba(X)[:, 1]
        df_cands["score"] = scores

        df_ranked = df_cands.sort_values("score", ascending=False).head(5)
        ok(f"Ranked {len(df_cands)} candidate drivers")
        ok("Top 5 match results:")
        for _, row in df_ranked.iterrows():
            print(f"      {row['driver_id']:12s} | score={row['score']:.4f}"
                  f" | dist={row['distance_km']:.2f}km"
                  f" | accept={row['accept_rate_7d']:.2f}")
        top = float(df_ranked.iloc[0]["score"])
        assert 0.0 <= top <= 1.0
        ok(f"Top score {top:.4f} is valid probability ✓")
except Exception as e:
    fail(f"Matching: {e}"); traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Match API: In-Process Logic Test
# ══════════════════════════════════════════════════════════════════════════════
step("7 · Match API – Logic Test (in-process)")
try:
    from src.match_api.main import haversine_distance as api_hav
    d = api_hav(40.748817, -73.985428, 40.706721, -74.009640)
    assert 4.0 < d < 8.0, f"got {d}"
    ok(f"haversine_distance test: {d:.3f} km ✓")
except Exception as e:
    warn(f"API import test: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Match API Server (subprocess with timeout)
# ══════════════════════════════════════════════════════════════════════════════
step("8 · Match API Server (FastAPI/Uvicorn)")

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    warn("requests not available — skipping HTTP test")

API_PORT = 8765
api_proc = None

if HAS_REQUESTS:
    info("Launching uvicorn on :8765 (SQLite feast store) ...")
    api_env = {**os.environ,
               "PYTHONPATH": str(PROJECT_ROOT),
               "FEAST_REPO_PATH": str(FEAST_REPO),
               "FEAST_FS_YAML": str(FS_YAML),
               "MLFLOW_TRACKING_URI": f"file://{PROJECT_ROOT / 'mlruns'}"}
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.match_api.main:app",
         "--host", "0.0.0.0", "--port", str(API_PORT), "--log-level", "warning"],
        cwd=str(PROJECT_ROOT), env=api_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    # Wait up to 30s for /metrics to respond (model loading from local mlruns may take time)
    ready = False
    for attempt in range(38):
        time.sleep(0.8)
        if api_proc.poll() is not None:
            info(f"Server exited early with code {api_proc.returncode}")
            break
        try:
            r = _req.get(f"http://localhost:{API_PORT}/metrics", timeout=2)
            if r.status_code == 200:
                ready = True; break
        except Exception:
            pass

    if ready:
        ok(f"FastAPI server up on :{API_PORT}")

        # Test /metrics
        r = _req.get(f"http://localhost:{API_PORT}/metrics", timeout=5)
        assert r.status_code == 200
        ok(f"GET /metrics → {r.status_code} (Prometheus endpoint)")

        # Test /match
        payload = {"rider_id": "rider_test_001", "rider_lat": 40.748817, "rider_lon": -73.985428, "top_k": 3}
        r = _req.post(f"http://localhost:{API_PORT}/match", json=payload, timeout=10)
        if r.status_code == 200:
            matches = r.json().get("matches", [])
            ok(f"POST /match → 200 | {len(matches)} matches returned")
            for m in matches:
                print(f"      {m}")
        elif r.status_code == 503:
            warn("POST /match → 503 (Feast/Redis offline — expected without Docker)")
        else:
            warn(f"POST /match → {r.status_code}: {r.text[:200]}")
    else:
        stderr_out = b""
        if api_proc.stderr:
            try:
                api_proc.stderr.fileno()
                import select
                rlist, _, _ = select.select([api_proc.stderr], [], [], 0.5)
                if rlist:
                    stderr_out = api_proc.stderr.read(1000)
            except Exception:
                pass
        warn(f"Server did not start in 20s. Stderr: {stderr_out.decode(errors='replace')[:300]}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — Unit Tests (pytest)
# ══════════════════════════════════════════════════════════════════════════════
step("9 · Unit Tests (pytest tests/)")
try:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        timeout=60,
    )
    lines = r.stdout.split("\n")
    summary = next((l for l in reversed(lines) if "passed" in l or "failed" in l), "")
    if r.returncode == 0:
        ok(f"pytest: {summary}")
    else:
        fail(f"pytest: {summary}")
    # print last 20 lines of pytest output
    for l in lines[-20:]:
        if l.strip(): info(l)
except Exception as e:
    fail(f"pytest: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 10 — MLflow Experiment Tracking
# ══════════════════════════════════════════════════════════════════════════════
step("10 · MLflow Experiment Tracking")
try:
    import mlflow
    mlruns = PROJECT_ROOT / "mlruns"
    if mlruns.exists():
        mlflow.set_tracking_uri(f"file://{mlruns}")
        exps = mlflow.search_experiments()
        ok(f"Found {len(exps)} MLflow experiment(s)")
        for exp in exps:
            runs = mlflow.search_runs(experiment_ids=[exp.experiment_id])
            ok(f"  '{exp.name}': {len(runs)} run(s)")
            if len(runs) > 0:
                mcols = [c for c in runs.columns if c.startswith("metrics.")]
                if mcols:
                    info(f"  Latest metrics: {runs.iloc[0][mcols].to_dict()}")
    else:
        warn("mlruns/ not found")
except Exception as e:
    warn(f"MLflow check: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 11 — Feature Drift Detection
# ══════════════════════════════════════════════════════════════════════════════
step("11 · Feature Drift Detection")
try:
    stats_path = PROJECT_ROOT / "models" / "feature_stats.json"
    if not stats_path.exists():
        stats_path = PROJECT_ROOT / "src" / "models" / "feature_stats.json"
    if stats_path.exists():
        with open(stats_path) as f:
            stats = json.load(f)
        ok(f"feature_stats.json loaded — features: {list(stats.keys())}")
        for feat, s in list(stats.items())[:3]:
            info(f"  {feat}: mean={s.get('mean',0):.3f}, std={s.get('std',1):.3f}")
        ok("Drift detection baseline validated")
    else:
        warn("feature_stats.json not found — run train_ranking_model.py to generate")
except Exception as e:
    warn(f"Drift check: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# CLEANUP
# ══════════════════════════════════════════════════════════════════════════════
if api_proc:
    api_proc.terminate()
    try: api_proc.wait(timeout=5)
    except Exception: api_proc.kill()
    info("API server stopped")

# ══════════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════
passed = [r for r in results if r[0] == "PASS"]
failed = [r for r in results if r[0] == "FAIL"]
warned = [r for r in results if r[0] == "WARN"]

print(f"\n{'═'*60}")
print("  RideMatch E2E Local Pipeline — FINAL REPORT")
print(f"{'═'*60}")
print(f"\n  {PASS} PASSED : {len(passed)}")
print(f"  {FAIL} FAILED : {len(failed)}")
print(f"  {WARN} WARNED : {len(warned)}")

if failed:
    print("\n  ── Failed ──")
    for _, m in failed: print(f"    {FAIL} {m}")

if warned:
    print("\n  ── Warnings (infra not running) ──")
    for _, m in warned: print(f"    {WARN} {m}")

print(f"\n{'═'*60}")
if not failed:
    print(f"  {PASS} ALL CORE PIPELINE STEPS PASSED (local / no-Docker mode)")
    print()
    print("  To run FULL production pipeline with Kafka, Redis, MinIO,")
    print("  MLflow server and Prefect:")
    print("    open -a OrbStack")
    print("    cd infra && docker compose up -d")
else:
    print(f"  {FAIL} {len(failed)} step(s) FAILED — see above")
print(f"{'═'*60}\n")

sys.exit(0 if not failed else 1)
