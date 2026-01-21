from prefect import flow, task
import subprocess
from datetime import datetime
import os


# === Prefect Task ===
@task(name="run_training_script", log_prints=True)
def run_training_script():
    """
    Task that executes the model training script (src/models/train_ranking_model.py).
    The script:
      - pulls historical data from Feast (offline store / MinIO)
      - trains a LightGBM model
      - logs metrics & model artifacts to MLflow
      - registers a model version in MLflow Model Registry
    """
    print("🚀 Starting RideMatch model training...")

    # Ensure required environment variables for MinIO, Feast, MLflow are loaded
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
        "AWS_REGION": "us-east-1",
        "AWS_S3_ENDPOINT": "http://localhost:9000",
        "AWS_S3_ADDRESSING_STYLE": "path",
        "ARROW_S3_USE_PATH_STYLE": "1",
        "MLFLOW_TRACKING_URI": "http://localhost:5050",  # MLflow runs on port 5050 (mapped from container port 5000)
    })

    # Command to run the training script
    cmd = ["python", "src/models/train_ranking_model.py"]

    # Execute the subprocess and capture output
    result = subprocess.run(cmd, capture_output=True, text=True)

    print("----- STDOUT -----")
    print(result.stdout)
    print("------------------")

    if result.returncode != 0:
        print("❌ Training script failed!")
        print(result.stderr)
        raise RuntimeError("Training script exited with errors.")

    print("✅ Training script completed successfully.")
    return result.stdout


# === Prefect Flow ===
@flow(name="train_and_register_model")
def train_flow():
    """
    Prefect Flow: orchestrates training and model registration.
    """
    print(f"🧠 Training flow started at {datetime.utcnow().isoformat()}")
    output = run_training_script()
    print(f"🎯 Flow completed at {datetime.utcnow().isoformat()}")
    return output


if __name__ == "__main__":
    train_flow()
