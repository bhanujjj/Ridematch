import os
import sys
import pandas as pd
import numpy as np
import mlflow
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from feast import FeatureStore
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load resources on startup (Feast Store, MLflow Model) and clean up on shutdown.
    """
    print("🚀 Starting RideMatch Match API...")

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
            # Fallback: finding latest version
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
            print(f"❌ Critical: Could not load any model. {inner_e}")
            sys.exit(1)

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
