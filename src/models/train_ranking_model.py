#!/usr/bin/env python3
"""
RideMatch Ranking Model Training
=================================

Trains a learning-to-rank model for matching riders to drivers using historical
features from Feast offline store.

Usage:
    python train_ranking_model.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Tuple

# Add feature_repo to path for Feast imports
project_root = Path(__file__).parent.parent.parent
feature_repo_path = project_root / "feature_repo"
sys.path.insert(0, str(feature_repo_path))

# Configure MinIO before importing Feast
# Import minio_config from feature_repo
try:
    import minio_config  # noqa: F401
except ImportError:
    # If minio_config not found, set environment variables directly
    os.environ.update({
        "AWS_ENDPOINT_URL": "http://localhost:9000",
        "AWS_S3_ENDPOINT": "http://localhost:9000",
        "AWS_S3_ADDRESSING_STYLE": "path",
        "ARROW_S3_USE_PATH_STYLE": "1",
        "AWS_S3_USE_HTTPS": "0",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
        "AWS_REGION": "us-east-1",
    })

from feast import FeatureStore
import mlflow
import mlflow.exceptions
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, accuracy_score, log_loss
import warnings
import urllib.request
from urllib.error import URLError

warnings.filterwarnings("ignore")


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on Earth (in km).
    
    Args:
        lat1, lon1: Latitude and longitude of first point (in degrees)
        lat2, lon2: Latitude and longitude of second point (in degrees)
    
    Returns:
        Distance in kilometers
    """
    # Convert latitude and longitude from degrees to radians
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    )
    c = 2 * np.arcsin(np.sqrt(a))
    
    # Earth radius in kilometers
    R = 6371.0
    
    return R * c


def load_driver_features(store: FeatureStore, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Load historical driver features from Feast offline store.
    
    Args:
        store: Feast FeatureStore instance
        start_date: Start timestamp for feature retrieval
        end_date: End timestamp for feature retrieval
    
    Returns:
        DataFrame with driver features
    """
    print(f"📊 Loading driver features from {start_date} to {end_date}...")
    
    # IMPORTANT: Feast point-in-time joins only populate features if the entity_df timestamps
    # actually correspond to real events in the offline store. If we "guess" driver IDs /
    # timestamps, Feast will return rows but feature values will be NULL.
    #
    # So we derive driver_id + timestamps from the offline parquet itself (MinIO/S3).
    s3_path = os.getenv("RIDEMATCH_OFFLINE_EVENTS_S3_PATH", "s3://ridematch-raw/driver_events/")
    endpoint_url = (
        os.getenv("S3_ENDPOINT_URL")
        or os.getenv("FEAST_S3_ENDPOINT_URL")
        or "http://localhost:9000"
    )
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

    if not access_key or not secret_key:
        raise RuntimeError(
            "Missing MinIO/S3 credentials in environment. "
            "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY before training."
        )

    # Read minimal columns to build entity_df
    storage_options = {
        "key": access_key,
        "secret": secret_key,
        "client_kwargs": {"endpoint_url": endpoint_url},
        # MinIO local dev is path-style + http
        "config_kwargs": {"s3": {"addressing_style": "path"}},
        "use_ssl": endpoint_url.startswith("https://"),
    }

    try:
        offline_ids = pd.read_parquet(
            s3_path,
            columns=["driver_id", "timestamp"],
            storage_options=storage_options,
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to read offline parquet from {s3_path}. "
            f"Check MinIO endpoint/creds env vars. Underlying error: {e}"
        ) from e

    offline_ids = offline_ids.rename(columns={"timestamp": "event_timestamp"})
    offline_ids = offline_ids.dropna(subset=["driver_id", "event_timestamp"])
    offline_ids["driver_id"] = offline_ids["driver_id"].astype(str)
    offline_ids = offline_ids[offline_ids["driver_id"].str.len() > 0]
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if start_ts.tz is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tz is None:
        end_ts = end_ts.tz_localize("UTC")

    offline_ids = offline_ids[
        (offline_ids["event_timestamp"] >= start_ts)
        & (offline_ids["event_timestamp"] <= end_ts)
    ]

    if offline_ids.empty:
        raise RuntimeError(
            f"No driver events found in offline store between {start_date} and {end_date}. "
            f"Confirm ETL uploaded data under {s3_path}."
        )

    # Sample entity rows to keep the query bounded
    max_entity_rows = int(os.getenv("RIDEMATCH_MAX_ENTITY_ROWS", "5000"))
    if len(offline_ids) > max_entity_rows:
        offline_ids = offline_ids.sample(n=max_entity_rows, random_state=42)

    entity_df = offline_ids.reset_index(drop=True)
    
    # Fetch historical features
    try:
        training_df = store.get_historical_features(
            entity_df=entity_df,
            features=[
                "driver_status:lat",
                "driver_status:lon",
                "driver_agg:accept_rate_7d",
                "driver_agg:avg_response_ms",
            ],
        ).to_df()
        
        print(f"✅ Loaded {len(training_df)} driver feature records")
        print(f"   Columns: {list(training_df.columns)}")
        print(f"   Non-null counts:\n{training_df.count()}")

        # Fail fast if Feast returned only null feature values (common PIT join mismatch)
        required = ["lat", "lon"]
        if all((c in training_df.columns and training_df[c].notna().sum() == 0) for c in required):
            raise RuntimeError(
                "Feast returned NULLs for lat/lon for all rows. "
                "This usually means the offline data timestamps in entity_df don't match the "
                "offline store events, or the offline store doesn't contain these columns."
            )

        return training_df
        
    except Exception as e:
        print(f"❌ Error loading features from Feast: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        print("   Full traceback:")
        traceback.print_exc()
        raise


def create_synthetic_driver_features(driver_ids: list, timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    """Create synthetic driver features for testing when Feast data is unavailable."""
    np.random.seed(42)
    rows = []
    for timestamp in timestamps[:10]:  # Limit for demo
        for driver_id in driver_ids[:20]:  # Limit for demo
            rows.append({
                "driver_id": driver_id,
                "event_timestamp": timestamp,
                "lat": 40.7128 + np.random.uniform(-0.1, 0.1),
                "lon": -74.0060 + np.random.uniform(-0.1, 0.1),
                "accept_rate_7d": np.random.uniform(0.5, 0.99),
                "avg_response_ms": np.random.randint(200, 1500),
            })
    return pd.DataFrame(rows)


def simulate_ride_requests(driver_features: pd.DataFrame, num_requests: int = 100) -> pd.DataFrame:
    """
    Simulate ride requests and create training examples.
    
    For each request:
    - Sample a random location (rider origin)
    - Sample multiple candidate drivers
    - Compute distance to each driver
    - Label closest driver as 1, others as 0
    
    Args:
        driver_features: DataFrame with driver features
        num_requests: Number of ride requests to simulate
    
    Returns:
        DataFrame with training examples (request_id, driver_id, features, label)
    """
    print(f"🚕 Simulating {num_requests} ride requests...")
    
    # Get unique driver snapshots (latest per driver)
    driver_latest = (
        driver_features
        .sort_values("event_timestamp")
        .groupby("driver_id")
        .tail(1)
        .reset_index(drop=True)
    )
    
    if len(driver_latest) == 0:
        raise ValueError("No driver features available. Check Feast data source.")
    
    print(f"   Found {len(driver_latest)} unique drivers")
    
    # Center coordinates (NYC area)
    center_lat, center_lon = 40.7128, -74.0060
    
    training_examples = []
    
    for request_id in range(num_requests):
        # Simulate rider origin (random location near center)
        rider_lat = center_lat + np.random.uniform(-0.05, 0.05)
        rider_lon = center_lon + np.random.uniform(-0.05, 0.05)
        
        # Sample 5-10 candidate drivers per request
        num_candidates = np.random.randint(5, min(11, len(driver_latest) + 1))
        candidates = driver_latest.sample(n=num_candidates, replace=False)
        
        # Compute distance for each candidate
        distances = []
        for _, driver_row in candidates.iterrows():
            dist = haversine_distance(
                rider_lat, rider_lon,
                driver_row["lat"], driver_row["lon"]
            )
            distances.append(dist)
        
        # Label: closest driver = 1, others = 0
        closest_idx = np.argmin(distances)
        
        # Create training examples
        for idx, (_, driver_row) in enumerate(candidates.iterrows()):
            label = 1 if idx == closest_idx else 0
            
            training_examples.append({
                "request_id": f"request_{request_id}",
                "driver_id": driver_row["driver_id"],
                "distance_km": distances[idx],
                "accept_rate_7d": driver_row["accept_rate_7d"],
                "avg_response_ms": driver_row["avg_response_ms"],
                "label": label,
            })
    
    training_df = pd.DataFrame(training_examples)
    print(f"✅ Created {len(training_df)} training examples")
    print(f"   Positive labels: {training_df['label'].sum()} ({100 * training_df['label'].mean():.1f}%)")
    
    return training_df


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> Tuple[Pipeline, dict]:
    """
    Train a ranking model and evaluate on validation set.
    
    Args:
        X_train: Training features
        y_train: Training labels
        X_val: Validation features
        y_val: Validation labels
    
    Returns:
        Trained model and evaluation metrics
    """
    print("🧠 Training LogisticRegression model...")
    
    # Train model (with imputation since some features (e.g., agg) may be missing initially)
    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("clf", LogisticRegression(random_state=42, max_iter=1000)),
        ]
    )
    model.fit(X_train, y_train)
    
    # Predictions
    y_train_pred = model.predict_proba(X_train)[:, 1]
    y_val_pred = model.predict_proba(X_val)[:, 1]
    y_val_pred_binary = model.predict(X_val)
    
    # Metrics
    metrics = {
        "train_auc": roc_auc_score(y_train, y_train_pred),
        "val_auc": roc_auc_score(y_val, y_val_pred),
        "train_accuracy": accuracy_score(y_train, model.predict(X_train)),
        "val_accuracy": accuracy_score(y_val, y_val_pred_binary),
        "train_log_loss": log_loss(y_train, y_train_pred),
        "val_log_loss": log_loss(y_val, y_val_pred),
    }
    
    print("✅ Model training completed")
    print(f"   Validation AUC: {metrics['val_auc']:.4f}")
    print(f"   Validation Accuracy: {metrics['val_accuracy']:.4f}")
    
    return model, metrics


def check_mlflow_available(tracking_uri: str) -> bool:
    """
    Check if MLflow server is available at the given URI.
    
    Args:
        tracking_uri: MLflow tracking URI
    
    Returns:
        True if MLflow server is accessible, False otherwise
    """
    if tracking_uri.startswith("file://") or tracking_uri.startswith("./"):
        # Local file tracking is always available
        return True
    
    try:
        # Extract host and port from URI
        if tracking_uri.startswith("http://"):
            url = tracking_uri.rstrip("/") + "/health"
        elif tracking_uri.startswith("https://"):
            url = tracking_uri.rstrip("/") + "/health"
        else:
            # Assume it's a file path
            return True
        
        # Try to connect (with short timeout)
        response = urllib.request.urlopen(url, timeout=2)
        return response.getcode() == 200
    except (URLError, ValueError, Exception):
        return False


def setup_mlflow_tracking(mlflow_tracking_uri: str, experiment_name: str) -> bool:
    """
    Setup MLflow tracking with fallback to local file tracking.
    
    Args:
        mlflow_tracking_uri: Desired MLflow tracking URI
        experiment_name: Experiment name
    
    Returns:
        True if using server tracking, False if using local file tracking
    """
    # Check if MLflow server is available
    if check_mlflow_available(mlflow_tracking_uri):
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        try:
            mlflow.set_experiment(experiment_name)
            print(f"✅ Connected to MLflow server: {mlflow_tracking_uri}")
            return True
        except Exception as e:
            print(f"⚠️  Failed to set experiment on MLflow server: {e}")
            print("   Falling back to local file tracking...")
    
    # Fallback to local file tracking
    local_mlruns = project_root / "mlruns"
    local_mlruns.mkdir(exist_ok=True)
    local_tracking_uri = f"file://{local_mlruns.absolute()}"
    mlflow.set_tracking_uri(local_tracking_uri)
    
    try:
        mlflow.set_experiment(experiment_name)
        print(f"📁 Using local MLflow tracking: {local_mlruns}")
        print(f"   (MLflow server not available at {mlflow_tracking_uri})")
        print(f"   To use server tracking, start MLflow: cd infra && docker-compose up -d mlflow")
        return False
    except Exception as e:
        print(f"❌ Failed to setup MLflow tracking: {e}")
        raise


def main():
    """Main training pipeline."""
    print("=" * 60)
    print("🚀 RideMatch Ranking Model Training")
    print("=" * 60)
    
    # Configuration
    feature_repo_path = project_root / "feature_repo"
    mlflow_tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050")
    experiment_name = "ridematch-ranking"
    model_name = "ridematch-ranker"
    
    print(f"📁 Feature repo: {feature_repo_path}")
    print(f"🔗 MLflow URI: {mlflow_tracking_uri}")
    print(f"📊 Experiment: {experiment_name}")
    print()
    
    # Setup MLflow tracking (with fallback to local)
    using_server = setup_mlflow_tracking(mlflow_tracking_uri, experiment_name)
    print()
    
    # Initialize Feast feature store
    try:
        store = FeatureStore(repo_path=str(feature_repo_path))
        print("✅ Feast feature store initialized")
    except Exception as e:
        print(f"❌ Failed to initialize Feast: {e}")
        sys.exit(1)
    
    # Define time range for historical features
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)  # Last 7 days
    
    # Load driver features
    driver_features = load_driver_features(store, start_date, end_date)
    
    if driver_features.empty:
        print("❌ No driver features loaded. Exiting.")
        sys.exit(1)
    
    # Simulate ride requests and create training data
    training_data = simulate_ride_requests(driver_features, num_requests=200)
    
    # Prepare features and labels
    feature_cols = ["distance_km", "accept_rate_7d", "avg_response_ms"]
    X = training_data[feature_cols]
    y = training_data["label"]
    
    # Train/validation split
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    print(f"\n📈 Training set: {len(X_train)} examples")
    print(f"📈 Validation set: {len(X_val)} examples")
    print()
    
    # Train model
    model, metrics = train_model(X_train, y_train, X_val, y_val)
    
    # Compute baseline feature statistics
    print("📊 Computing baseline feature statistics...")
    stats = {}
    for col in feature_cols:
        series = X_train[col]
        stats[col] = {
            "mean": float(series.mean()),
            "std": float(series.std()),
            "p50": float(series.median()),
            "p95": float(series.quantile(0.95)),
            "min": float(series.min()),
            "max": float(series.max())
        }
    
    # Save stats to local file
    import json
    stats_path = project_root / "models" / "feature_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"✅ Feature stats saved to {stats_path}")
    
    # Log to MLflow
    print("\n📝 Logging to MLflow...")
    with mlflow.start_run() as run:
        # Log parameters
        mlflow.log_params({
            "model_type": "LogisticRegression",
            "features": ",".join(feature_cols),
            "train_size": len(X_train),
            "val_size": len(X_val),
            "num_requests": len(training_data["request_id"].unique()),
        })
        
        # Log metrics
        mlflow.log_metrics(metrics)
        
        # Log model with fallback for version compatibility
        # MLflow 3.x client with 2.x server has API compatibility issues
        # The issue: log_model() tries to create a "logged model" via /api/2.0/mlflow/logged-models
        # which doesn't exist in MLflow 2.10.0 server
        model_path = None
        model_logged = False
        
        try:
            # Try the standard approach first
            model_path = mlflow.sklearn.log_model(
                model,
                "model",
            )
            print("✅ Model logged to MLflow")
            print(f"   Model path: {model_path}")
            model_logged = True
            
            # Log feature stats artifact
            mlflow.log_artifact(str(stats_path), artifact_path="feature_stats")
            print("✅ Feature stats logged to MLflow")
            
        except mlflow.exceptions.MlflowException as e:
            if "logged-models" in str(e) or "404" in str(e):
                # API compatibility issue - log_model() calls unsupported endpoint
                print(f"⚠️  API compatibility issue with log_model(): {str(e)[:100]}...")
                print("   Skipping MLflow artifact logging (metrics and parameters are still saved)")
                print("   Saving model locally instead...")
                
                # Save model locally as fallback
                local_models_dir = project_root / "models" / "saved"
                local_models_dir.mkdir(parents=True, exist_ok=True)
                local_model_path = local_models_dir / f"{model_name}_{run.info.run_id}.pkl"
                
                import pickle
                with open(local_model_path, "wb") as f:
                    pickle.dump(model, f)
                
                print(f"   ✅ Model saved locally: {local_model_path}")
                print("   This is a known issue with MLflow 3.x client and 2.x server")
                model_path = str(local_model_path)
                model_logged = False
            else:
                # Re-raise if it's a different error
                raise
        except OSError as e:
            # Handle read-only filesystem or other OS errors
            if "Read-only file system" in str(e) or "30" in str(e):
                print(f"⚠️  Cannot write artifacts to server storage: {e}")
                print("   Skipping MLflow artifact logging (metrics and parameters are still saved)")
                print("   Saving model locally instead...")
                
                # Save model locally as fallback
                local_models_dir = project_root / "models" / "saved"
                local_models_dir.mkdir(parents=True, exist_ok=True)
                local_model_path = local_models_dir / f"{model_name}_{run.info.run_id}.pkl"
                
                import pickle
                with open(local_model_path, "wb") as f:
                    pickle.dump(model, f)
                
                print(f"   ✅ Model saved locally: {local_model_path}")
                print("   This may be due to server artifact storage configuration")
                model_path = str(local_model_path)
                model_logged = False
            else:
                raise
        
        print(f"   Run ID: {run.info.run_id}")
        
        # Register model separately (only if model was successfully logged)
        if model_logged and model_path:
            try:
                model_uri = f"runs:/{run.info.run_id}/model"
                mlflow.register_model(
                    model_uri=model_uri,
                    name=model_name,
                )
                print(f"✅ Model registered as '{model_name}'")
            except Exception as e:
                print(f"⚠️  Model registration failed (this is optional): {e}")
                print(f"   Model is still logged at: {model_uri}")
                print(f"   You can register it manually later from the MLflow UI")
    
    print("\n" + "=" * 60)
    print("✅ Training pipeline completed successfully!")
    print("=" * 60)
    print(f"\n📊 Model Performance:")
    print(f"   Validation AUC: {metrics['val_auc']:.4f}")
    print(f"   Validation Accuracy: {metrics['val_accuracy']:.4f}")
    
    # Show where to view results
    if using_server:
        print(f"\n🔗 View results in MLflow UI: {mlflow_tracking_uri}")
    else:
        local_mlruns = project_root / "mlruns"
        print(f"\n📁 Results saved locally: {local_mlruns}")
        print(f"   To view in MLflow UI, start server: cd infra && docker-compose up -d mlflow")
        print(f"   Then copy mlruns/ to mlflow_data/ or use: mlflow ui --backend-store-uri file://{local_mlruns}")


if __name__ == "__main__":
    main()
