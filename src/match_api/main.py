import os
import sys
import pandas as pd
import numpy as np
import mlflow
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from feast import FeatureStore
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import json
from collections import deque

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
FEATURE_VALUES = Histogram(
    "feature_values",
    "Distribution of feature values",
    ["feature_name"],
    buckets=[0, 1, 2, 5, 10, 20, 50, 100]  # Generic buckets, adjustable
)
FEATURE_DRIFT = Gauge(
    "feature_drift_score",
    "Percentage drift (p95 delta) from training baseline",
    ["feature_name"]
)


# --- Configuration ---
PROJECT_ROOT = Path(__file__).parent.parent.parent
FEATURE_REPO_PATH = PROJECT_ROOT / "feature_repo"
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050")
MODEL_NAME = "ridematch-ranker"
# In a real scenario, we might use a stage like "Production", but locally we may need to find the latest version.
# For simplicity, we'll try to load "models:/ridematch-ranker/Production" or fallback to latest.
MODEL_URI = f"models:/{MODEL_NAME}/Production"

# Ensure feature_repo is in path for Feast to find definitions if needed
sys.path.insert(0, str(FEATURE_REPO_PATH))

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
    try:
        store = FeatureStore(repo_path=str(FEATURE_REPO_PATH))
        resources["feature_store"] = store
        print(f"✅ Feast FeatureStore initialized (repo: {FEATURE_REPO_PATH})")
    except Exception as e:
        print(f"❌ Failed to initialize Feast FeatureStore: {e}")
        sys.exit(1)

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
                sys.exit(1)
                
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
                sys.exit(1)

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

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/match", response_model=MatchResponse)
@MATCH_REQUEST_LATENCY.time()
async def match_drivers(request: MatchRequest):
    """
    Rank candidate drivers for a given rider request.
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
        
    # Track Feature Drift
    drift_detector = resources.get("drift_detector")
    if drift_detector:
        # Iterate over all candidates
        for _, row in df_candidates.iterrows():
            for feature in ["distance_km", "accept_rate_7d", "avg_response_ms"]:
                val = row.get(feature)
                if val is not None:
                    # Log to Histogram
                    FEATURE_VALUES.labels(feature_name=feature).observe(val)
                    # Update Drift Detector
                    drift_detector.observe(feature, val)
    
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
