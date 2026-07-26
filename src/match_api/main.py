import json
import os
import sys
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from feast import FeatureStore
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .schemas import MatchRequest, MatchResponse, MatchResponseItem
from .utils import haversine_distance

# --- Metrics ---
MATCH_REQUEST_LATENCY = Histogram(
    "match_request_latency_seconds",
    "Time spent processing match request",
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]
)
MATCH_ERRORS = Counter(
    "match_errors_total",
    "Total number of errors in match requests",
    ["error_type"]
)
PREDICTION_SCORES = Histogram(
    "prediction_scores",
    "Distribution of driver match scores",
    buckets=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
)
FEATURE_MISSING_COUNT = Counter(
    "feature_missing_total",
    "Total number of missing feature values",
    ["feature_name"]
)
# One Histogram per feature rather than a single labelled Histogram.
#
# A labelled Histogram shares one bucket layout across every label value, and
# these features live on wildly different scales: accept_rate_7d is 0-1, while
# avg_response_ms runs into the thousands. With shared buckets every accept-rate
# observation collapses into the first bucket and the distribution is unreadable.
FEATURE_VALUE_HISTOGRAMS = {
    "distance_km": Histogram(
        "feature_distance_km",
        "Distribution of rider-to-driver distance (km)",
        buckets=[0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 35],
    ),
    "accept_rate_7d": Histogram(
        "feature_accept_rate_7d",
        "Distribution of driver 7-day accept rate",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
    ),
    "avg_response_ms": Histogram(
        "feature_avg_response_ms",
        "Distribution of driver average response time (ms)",
        buckets=[100, 250, 500, 750, 1000, 1500, 2000, 3000, 5000],
    ),
}
FEATURE_DRIFT = Gauge(
    "feature_drift_score",
    "Percentage drift (p95 delta) from training baseline",
    ["feature_name"]
)


# --- Configuration ---
PROJECT_ROOT = Path(__file__).parent.parent.parent
FEATURE_REPO_PATH = PROJECT_ROOT / "feature_repo"
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050")
# Unset/empty by default so local dev and the existing test suite need no
# extra setup; set MATCH_API_KEY to require it. Deliberately not required
# for /health or /ready -- probes/orchestrators must reach those unauthenticated.
MATCH_API_KEY = os.getenv("MATCH_API_KEY", "")
MODEL_NAME = "ridematch-ranker"
# In a real scenario, we might use a stage like "Production", but locally we may need to find the latest version.
# For simplicity, we'll try to load "models:/ridematch-ranker/Production" or fallback to latest.
MODEL_URI = f"models:/{MODEL_NAME}/Production"

# Ensure feature_repo is in path for Feast to find definitions if needed
sys.path.insert(0, str(FEATURE_REPO_PATH))
# Must happen before FeatureStore(...) below: feature_store.yaml's
# online_store.connection_string is "${REDIS_HOST}:${REDIS_PORT}", expanded
# by Feast via os.path.expandvars at parse time. FeatureStore's constructor
# doesn't import feature_views.py (that only happens on repo-scanning
# operations like `apply`), so nothing else guarantees these are set.
import minio_config  # noqa: E402,F401

# Global variables for resources
resources = {}

class DriftDetector:
    def __init__(self, baseline_stats: dict, window_size: int = 1000, compute_every: int = 100):
        self.baseline_stats = baseline_stats
        self.window_size = window_size
        self.compute_every = compute_every
        self.buffers = {}
        self.counters = {}
        
        # Initialize buffers for each feature in baseline
        for feature in baseline_stats:
            self.buffers[feature] = deque(maxlen=window_size)
            self.counters[feature] = 0
            
    def observe(self, feature_name: str, value: float):
        if feature_name not in self.baseline_stats:
            return

        # Add to buffer
        self.buffers[feature_name].append(value)
        self.counters[feature_name] += 1

        # Compute drift periodically
        if self.counters[feature_name] >= self.compute_every:
            self._compute_drift(feature_name)
            self.counters[feature_name] = 0

    def observe_many(self, feature_name: str, values):
        """
        Bulk version of observe(). The hot path feeds ~100 values per request,
        so we extend the ring buffer in one call and recompute drift at most
        once, instead of once per element.
        """
        if feature_name not in self.baseline_stats:
            return
        n = len(values)
        if n == 0:
            return
        self.buffers[feature_name].extend(values)
        self.counters[feature_name] += n
        if self.counters[feature_name] >= self.compute_every:
            self._compute_drift(feature_name)
            self.counters[feature_name] = 0


    def _compute_drift(self, feature_name: str):
        buffer = self.buffers[feature_name]
        if not buffer:
            return
            
        # Calculate current p95
        current_p95 = np.percentile(buffer, 95)
        baseline_p95 = self.baseline_stats[feature_name]["p95"]
        
        # Avoid division by zero
        if baseline_p95 == 0:
            drift = abs(current_p95 - baseline_p95)
        else:
            drift = abs(current_p95 - baseline_p95) / baseline_p95
            
        # Update Prometheus Gauge
        FEATURE_DRIFT.labels(feature_name=feature_name).set(drift)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load resources on startup (Feast Store, MLflow Model, Feature Stats) and clean up on shutdown.
    """
    print("🚀 Starting RideMatch Match API...")
    
    if os.getenv("SKIP_RESOURCES_INIT"):
        print("⚠️  SKIP_RESOURCES_INIT set. Skipping Feast/MLflow connection. API will be in degraded mode (for CI/Smoke tests).")
        yield
        print("🛑 Shutting down RideMatch Match API...")
        resources.clear()
        return

    # 1. Initialize Feast Feature Store
    # Support FEAST_FS_YAML env var to point to an alternate feature_store yaml
    # (e.g., feature_store_local.yaml with SQLite instead of Redis for local dev)
    try:
        feast_fs_yaml = os.getenv("FEAST_FS_YAML")
        if feast_fs_yaml and Path(feast_fs_yaml).exists():
            store = FeatureStore(repo_path=str(FEATURE_REPO_PATH), fs_yaml_file=feast_fs_yaml)
            print(f"✅ Feast FeatureStore initialized (yaml: {feast_fs_yaml})")
        else:
            store = FeatureStore(repo_path=str(FEATURE_REPO_PATH))
            print(f"✅ Feast FeatureStore initialized (repo: {FEATURE_REPO_PATH})")
        resources["feature_store"] = store
    except Exception as e:
        # Do not sys.exit() from inside a lifespan handler: it kills the worker
        # mid-startup and the orchestrator sees a crash loop with no diagnostics.
        # Come up in a degraded state instead -- /health stays 200 so the
        # container is debuggable, /ready returns 503 so no traffic is routed.
        print(f"❌ Failed to initialize Feast FeatureStore: {e}")
        resources["startup_error"] = f"feast: {e}"

    # 2. Load Ranking Model from MLflow
    try:
        # Check if MLflow server is reachable, else warn/fallback logic could be added here.
        # For this assignment, we assume MLflow is running or we have appropriate credentials/setup.
        mlflow.set_tracking_uri(MLFLOW_URI)
        print(f"🔗 MLflow URI: {MLFLOW_URI}")
        
        # Load model as a PyFunc model
        model = mlflow.sklearn.load_model(MODEL_URI) 
        resources["model"] = model
        print(f"✅ Model loaded from {MODEL_URI}")
    except Exception as e:
        print(f"⚠️  Failed to load model from {MODEL_URI}: {e}")
        print("   Attempting to load latest version instead...")
        try:
            client = mlflow.MlflowClient()
            latest_versions = client.get_latest_versions(MODEL_NAME, stages=["None", "Staging", "Production"])
            if not latest_versions:
                raise RuntimeError(f"No versions found for model {MODEL_NAME}")
            
            latest_version = latest_versions[-1]
            fallback_uri = f"runs:/{latest_version.run_id}/model"
            model = mlflow.sklearn.load_model(fallback_uri)
            resources["model"] = model
            print(f"✅ Model loaded from fallback: {fallback_uri}")
        except Exception as inner_e:
            print(f"⚠️  MLflow lookup failed: {inner_e}")
            print("   Attempting to load local .pkl model from models/saved/ ...")
            
            # Local fallback: Find newest .pkl file
            import glob
            import pickle
            
            local_models_dir = PROJECT_ROOT / "models" / "saved"
            pkl_files = glob.glob(str(local_models_dir / "*.pkl"))
            
            if not pkl_files:
                print(f"❌ Critical: No model found in MLflow OR local {local_models_dir}")
                print(f"Original error: {inner_e}")
                resources["startup_error"] = f"model: no model in MLflow or {local_models_dir}"
            else:
                # Get latest file by mtime
                latest_pkl = max(pkl_files, key=os.path.getmtime)
                print(f"   Found local model: {latest_pkl}")

                try:
                    with open(latest_pkl, "rb") as f:
                        model = pickle.load(f)
                    resources["model"] = model
                    print(f"✅ Model loaded from local file: {latest_pkl}")
                except Exception as load_e:
                    print(f"❌ Failed to load local pickle: {load_e}")
                    resources["startup_error"] = f"model: {load_e}"

    # 3. Load Feature Statistics for Drift Detection
    try:
        # Ideally load from MLflow artifact, but for simplicity/speed we load local JSON generated by training
        # Valid assumption since we are in the same repo structure
        stats_path = PROJECT_ROOT / "src/models/feature_stats.json"
        # Fallback to model directory if not found in src/models (training script saves to src/models usually? No, it saved to "models/feature_stats.json" relative to project root)
        if not stats_path.exists():
            stats_path = PROJECT_ROOT / "models" / "feature_stats.json"
            
        if stats_path.exists():
            with open(stats_path, "r") as f:
                stats = json.load(f)
            resources["drift_detector"] = DriftDetector(stats)
            print(f"✅ Loaded feature stats for drift detection: {list(stats.keys())}")
        else:
            print(f"⚠️  Feature stats not found at {stats_path}. Drift detection disabled.")
            resources["drift_detector"] = None
    except Exception as e:
        print(f"❌ Failed to load feature stats: {e}")
        resources["drift_detector"] = None

    yield
    print("🛑 Shutting down RideMatch Match API...")
    resources.clear()

app = FastAPI(title="RideMatch Real-Time API", lifespan=lifespan)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """
    Gate /match behind a shared-secret header when MATCH_API_KEY is set.
    A no-op when it isn't, so local dev / CI need no extra configuration.
    """
    if MATCH_API_KEY and x_api_key != MATCH_API_KEY:
        MATCH_ERRORS.labels(error_type="unauthorized").inc()
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    """
    Liveness probe. Answers "is this process alive and serving HTTP?" only.
    Deliberately never fails on missing dependencies -- a liveness probe that
    checks downstreams turns a Redis blip into a cluster-wide restart storm.
    """
    return {"status": "alive"}


@app.get("/ready")
async def ready(response: Response):
    """
    Readiness probe. Answers "should this instance receive traffic?" -- which
    requires both the feature store and the model to be loaded.
    """
    detail = {
        "feature_store": resources.get("feature_store") is not None,
        "model": resources.get("model") is not None,
        "drift_detection": resources.get("drift_detector") is not None,
    }
    ok = detail["feature_store"] and detail["model"]
    if not ok:
        response.status_code = 503
        detail["error"] = resources.get("startup_error", "resources not initialized")
    detail["status"] = "ready" if ok else "not_ready"
    return detail

@app.post("/match", response_model=MatchResponse, dependencies=[Depends(require_api_key)])
@MATCH_REQUEST_LATENCY.time()
def match_drivers(request: MatchRequest):
    """
    Rank candidate drivers for a given rider request.

    NOTE: deliberately a *sync* `def`, not `async def`. The body does blocking
    work -- a synchronous Redis round-trip via Feast and a CPU-bound sklearn
    `predict_proba`. Declaring it `async` would run that blocking code directly
    on the event loop, serialising every concurrent request behind the slowest
    one and destroying tail latency under load. As a sync endpoint FastAPI runs
    it in the threadpool, so requests actually overlap.
    """
    store = resources.get("feature_store")
    model = resources.get("model")
    
    if not store or not model:
        MATCH_ERRORS.labels(error_type="initialization_error").inc()
        raise HTTPException(status_code=503, detail="Service not initialized properly")

    # 1. Select Candidate Drivers
    # In a real system, this would be a geospatial query (Geohash/H3/S2).
    # Here we simulate candidates "driver_0" to "driver_99".
    candidate_driver_ids = [f"driver_{i}" for i in range(100)]
    
    # 2. Fetch Online Features from Feast
    # We need:
    # - driver_status:lat, driver_status:lon
    # - driver_agg:accept_rate_7d, driver_agg:avg_response_ms
    features_to_fetch = [
        "driver_status:lat",
        "driver_status:lon",
        "driver_agg:accept_rate_7d",
        "driver_agg:avg_response_ms",
    ]
    
    try:
        online_features = store.get_online_features(
            features=features_to_fetch,
            entity_rows=[{"driver_id": d_id} for d_id in candidate_driver_ids]
        ).to_dict()
    except Exception as e:
        MATCH_ERRORS.labels(error_type="feast_error").inc()
        raise HTTPException(status_code=500, detail=f"Feast feature retrieval failed: {e}")

    # Convert to DataFrame for easy processing
    df_candidates = pd.DataFrame(online_features)
    
    # Track missing features
    # Feast returns None for missing values, which usually become NaN in pandas for numeric columns
    # or None for object columns.
    for col in df_candidates.columns:
        if col == "driver_id":
            continue
        missing_count = df_candidates[col].isna().sum()
        if missing_count > 0:
            FEATURE_MISSING_COUNT.labels(feature_name=col).inc(missing_count)
    
    # 3. Preprocessing & Distance Calculation
    # We need to filter out drivers who might have missing essential location data
    # (Though in prod we might have fallbacks, here we just filter for safety)    
    # Note: Feast returns None for missing values.
    
    # Ensure columns exist (in case Feast returns empty for everything)
    expected_cols = ["driver_id", "lat", "lon", "accept_rate_7d", "avg_response_ms"]
    for col in expected_cols:
         if col not in df_candidates.columns:
             # Feast feature names might be fully qualified or not depending on version/config
             # Usually get_online_features returns feature names without view prefix if configured,
             # but let's check. 
             # Actually, Feast results keys usually match the requested feature names (e.g. "driver_status:lat")
             # or stripped names ("lat").
             # Let's handle the keys returned by Feast.
             pass

    # Rename keys to simple names if they have colons
    # keys are: "driver_id", "driver_status:lat", etc.
    rename_map = {}
    for col in df_candidates.columns:
        if ":" in col:
            rename_map[col] = col.split(":")[1]
    df_candidates.rename(columns=rename_map, inplace=True)
    
    # Drop rows where critical location data is missing
    df_candidates.dropna(subset=["lat", "lon"], inplace=True)
    
    if df_candidates.empty:
        return MatchResponse(matches=[])

    # Calculate Distance
    # Vectorized Haversine
    df_candidates["distance_km"] = haversine_distance(
        request.rider_lat, request.rider_lon,
        df_candidates["lat"].values, df_candidates["lon"].values
    )
    
    # 4. Prepare Inference Vector
    # Model expects: ["distance_km", "accept_rate_7d", "avg_response_ms"]
    inference_cols = ["distance_km", "accept_rate_7d", "avg_response_ms"]
    
    # Handle missing features for inference (SimpleImputer logic is inside pipeline, 
    # but we need to ensure NaNs are passed correctly if missing)
    # Feast might return None, which pandas converts to NaN or None.
    # Sklearn pipeline with SimpleImputer will handle NaN.
    
    X_score = df_candidates[inference_cols]
    
    # 5. Predict Scores
    try:
        # predict_proba returns [prob_class_0, prob_class_1]
        # We want probability of class 1 (match)
        scores = model.predict_proba(X_score)[:, 1]
    except Exception as e:
        MATCH_ERRORS.labels(error_type="inference_error").inc()
        # If model doesn't support predict_proba or other error
        raise HTTPException(status_code=500, detail=f"Model inference failed: {e}")
        
    df_candidates["score"] = scores
    
    # Track prediction scores
    for s in scores:
        PREDICTION_SCORES.observe(s)

    # Track feature values + drift.
    #
    # This used to be `for _, row in df_candidates.iterrows()` with a nested
    # per-feature loop -- 100 candidates x 3 features of pandas row-boxing on
    # every single request, which dominated the p99. Now we pull each column
    # out as a numpy array once and bulk-extend the drift buffers.
    drift_detector = resources.get("drift_detector")
    if drift_detector:
        for feature in ("distance_km", "accept_rate_7d", "avg_response_ms"):
            if feature not in df_candidates.columns:
                continue
            vals = pd.to_numeric(df_candidates[feature], errors="coerce").to_numpy()
            vals = vals[~np.isnan(vals)]
            if vals.size == 0:
                continue
            hist = FEATURE_VALUE_HISTOGRAMS.get(feature)
            if hist is not None:
                for v in vals:
                    hist.observe(v)
            drift_detector.observe_many(feature, vals)


    # 6. Rank and Filter
    df_ranked = df_candidates.sort_values(by="score", ascending=False).head(request.top_k)
    
    matches = []
    for _, row in df_ranked.iterrows():
        matches.append(MatchResponseItem(
            driver_id=row["driver_id"],
            score=float(row["score"]),
            distance_km=float(row["distance_km"])
        ))
        
    return MatchResponse(matches=matches)
