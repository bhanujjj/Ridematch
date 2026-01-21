# Prefect & MLflow Fixes Summary

## ✅ Issues Fixed

### 1. Prefect Worker Error - `PREFECT_API_URL` must be set
**Problem**: Worker couldn't connect to Prefect server
**Solution**: Created `start_worker.sh` script that sets `PREFECT_API_URL="http://127.0.0.1:4200/api"`

### 2. MLflow Not Running
**Problem**: MLflow container was stopped and had no startup command
**Solution**: 
- Added `command` to docker-compose.yml to start MLflow server
- Fixed database path issue (was trying to access `/mlflow.db` which didn't exist in container)
- MLflow now runs on **port 5050** (mapped from container port 5000)

### 3. Flows Not Appearing in Prefect UI
**Problem**: Flows need to be run or served to appear in UI
**Solution**: 
- Created deployment guide with multiple options
- Flows will appear after running them once
- Created `serve_flows.py` for serving flows continuously

### 4. Wrong MLflow Port in Code
**Problem**: `train_flow.py` was using port 5000, but MLflow runs on 5050
**Solution**: Updated `MLFLOW_TRACKING_URI` to `http://localhost:5050`

## 📋 Current Status

### ✅ Working
- Prefect server: http://localhost:4200
- Prefect worker: Running and connected
- MLflow: http://localhost:5050 (fixed database path)
- Flows: Can be run and will appear in UI

### 📝 Files Created/Modified

1. **`prefect/start_worker.sh`** - Starts worker with correct API URL
2. **`prefect/setup_prefect.sh`** - One-time Prefect configuration
3. **`prefect/flows/deploy_flows.py`** - Attempts to deploy flows (Prefect 3.x requires storage)
4. **`prefect/flows/serve_flows.py`** - Serves flows for local development
5. **`prefect/FLOW_DEPLOYMENT_GUIDE.md`** - Complete guide on deploying flows
6. **`infra/docker-compose.yml`** - Fixed MLflow command and database path
7. **`prefect/flows/train_flow.py`** - Fixed MLflow port (5000 → 5050)

## 🚀 Quick Start

### 1. Start Services
```bash
cd infra
docker-compose up -d
```

### 2. Start Prefect Worker
```bash
cd prefect
bash start_worker.sh
```

### 3. Run a Flow (to see it in UI)
```bash
conda activate ridematch
python prefect/flows/train_flow.py
```

### 4. Access UIs
- **Prefect UI**: http://localhost:4200
- **MLflow UI**: http://localhost:5050

## 🔍 Verification

### Check Prefect Flows
```bash
conda activate ridematch
PREFECT_API_URL="http://127.0.0.1:4200/api" prefect flow ls
```

### Check MLflow
```bash
curl http://localhost:5050
# Should return HTML (MLflow UI)
```

### Check Services
```bash
docker ps | grep -E "prefect|mlflow"
# Should show both containers running
```

## 📚 Next Steps

1. **Run flows** - Execute flows to see them in Prefect UI
2. **Serve flows** - Use `serve_flows.py` to keep flows available in UI
3. **Create deployments** - For production, create deployment YAML files
4. **Schedule flows** - Set up schedules in Prefect UI for automated runs

## 🎯 Key Points

- **MLflow runs on port 5050** (not 5000)
- **Prefect API URL**: `http://127.0.0.1:4200/api`
- **Flows appear in UI after running them**
- **Worker must be running to execute flows from work pool**

