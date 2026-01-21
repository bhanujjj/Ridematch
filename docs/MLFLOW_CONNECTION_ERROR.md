# MLflow Connection Error - Explanation & Fix

## What is the Error?

```
ConnectionRefusedError: [Errno 61] Connection refused
mlflow.exceptions.MlflowException: API request to http://localhost:5050/api/2.0/mlflow/experiments/get-by-name failed
```

## Why Did This Error Occur?

### Root Cause
The training script (`train_ranking_model.py`) tried to connect to the **MLflow tracking server** at `http://localhost:5050`, but the server wasn't running.

### What is MLflow?
MLflow is a tool for tracking machine learning experiments. It stores:
- Model parameters (hyperparameters)
- Metrics (AUC, accuracy, etc.)
- Model artifacts (saved models)
- Experiment history

### Why Do We Need MLflow Running?
When you train a model, the script needs to:
1. **Log metrics** (validation AUC, accuracy, etc.)
2. **Save the model** for later use
3. **Track experiments** so you can compare different runs

The script tries to connect to MLflow server to store this information. If the server isn't running, the connection fails.

## The Fix

I've updated the training script to handle this gracefully:

### ✅ **Automatic Fallback**
- If MLflow server is available → Uses server tracking (shared, accessible via UI)
- If MLflow server is NOT available → Falls back to **local file tracking** (saves to `mlruns/` folder)

### ✅ **Better Error Messages**
The script now:
- Checks if MLflow server is running before trying to connect
- Provides clear instructions if server is not available
- Still trains the model even if MLflow server is down

## How to Use

### Option 1: Run Without MLflow Server (Easiest)
```bash
python src/models/train_ranking_model.py
```
- Model will train successfully
- Results saved to `mlruns/` folder locally
- You can view them later when MLflow server is running

### Option 2: Start MLflow Server First (Recommended)
```bash
# Start MLflow server
cd infra
docker-compose up -d mlflow

# Wait a few seconds for it to start, then run training
cd ../..
python src/models/train_ranking_model.py
```

Then view results at: **http://localhost:5050**

### Option 3: View Local Results Later
If you trained without the server, you can view local results:
```bash
# Start MLflow UI pointing to local mlruns folder
mlflow ui --backend-store-uri file://$(pwd)/mlruns
```

## Technical Details

### Connection Check
The script now checks if MLflow is available by:
1. Trying to connect to the `/health` endpoint
2. Using a 2-second timeout (doesn't hang)
3. Falling back to local file tracking if connection fails

### Local File Tracking
When MLflow server is unavailable:
- Results saved to: `RideMatch/mlruns/`
- Same format as server tracking
- Can be imported to MLflow server later

## Verification

### Check if MLflow Server is Running
```bash
# Check Docker container
docker ps | grep mlflow

# Test connection
curl http://localhost:5050/health
```

### Check Local Results
```bash
# List local experiments
ls -la mlruns/
```

## Summary

**Before Fix:**
- ❌ Script crashed if MLflow server wasn't running
- ❌ No way to train without starting server first

**After Fix:**
- ✅ Script works with or without MLflow server
- ✅ Automatic fallback to local tracking
- ✅ Clear error messages and instructions
- ✅ Model training always succeeds

The error is now handled gracefully, and you can train models even when the MLflow server isn't running!
