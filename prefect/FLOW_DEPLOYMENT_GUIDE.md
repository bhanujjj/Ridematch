# Prefect Flow Deployment Guide

## Problem

You don't see flows in the Prefect UI because:
1. **Flows need to be deployed or served** - Just defining a flow doesn't make it appear in the UI
2. **MLflow wasn't running** - Fixed by adding the server command to docker-compose.yml

## Solutions

### Solution 1: Run Flows Directly (Simplest)

Run flows directly - they will appear in the UI after running:

```bash
conda activate ridematch
cd /Users/bhanujbhalla/Desktop/Projects/RideMatch

# Run ETL flow
python prefect/flows/etl_flow.py

# Run training flow
python prefect/flows/train_flow.py
```

After running, check the Prefect UI at http://localhost:4200 - you should see flow runs.

### Solution 2: Use flow.serve() (Recommended for Local Development)

Serve flows so they're always available in the UI:

```bash
conda activate ridematch
cd /Users/bhanujbhalla/Desktop/Projects/RideMatch/prefect/flows

# Serve ETL flow (in one terminal)
python -c "from etl_flow import ridematch_ingest_flow; ridematch_ingest_flow.serve(name='ridematch-ingest', tags=['etl'])"

# Serve training flow (in another terminal)
python -c "from train_flow import train_flow; train_flow.serve(name='train-and-register-model', tags=['training', 'mlflow'])"
```

Or use the serve script:
```bash
python serve_flows.py
```

### Solution 3: Create Deployments (For Production)

For Prefect 3.x, you need to create deployment YAML files:

1. Create `prefect/deployments/ridematch-ingest.yaml`:
```yaml
name: ridematch-ingest-deployment
flow_name: ridematch_ingest
entrypoint: prefect/flows/etl_flow.py:ridematch_ingest_flow
work_pool:
  name: ridematch-pool
  work_queue_name: ridematch-queue
```

2. Create `prefect/deployments/train-model.yaml`:
```yaml
name: train-model-deployment
flow_name: train_and_register_model
entrypoint: prefect/flows/train_flow.py:train_flow
work_pool:
  name: ridematch-pool
  work_queue_name: ridematch-queue
```

3. Deploy:
```bash
prefect deploy prefect/deployments/ridematch-ingest.yaml
prefect deploy prefect/deployments/train-model.yaml
```

## MLflow Access

MLflow is now running on **port 5050** (not 5000):
- **URL**: http://localhost:5050
- **Fixed in**: `prefect/flows/train_flow.py` (changed MLFLOW_TRACKING_URI to port 5050)
- **Docker**: Container port 5000 is mapped to host port 5050

## Quick Start

1. **Start MLflow** (if not running):
   ```bash
   cd infra
   docker-compose up -d mlflow
   ```

2. **Start Prefect Server** (if not running):
   ```bash
   cd infra
   docker-compose up -d prefect
   ```

3. **Start Prefect Worker**:
   ```bash
   cd prefect
   bash start_worker.sh
   ```

4. **Run a flow** (to see it in UI):
   ```bash
   conda activate ridematch
   python prefect/flows/train_flow.py
   ```

5. **Check UI**:
   - Prefect UI: http://localhost:4200
   - MLflow UI: http://localhost:5050

## Verification

- **Prefect UI**: http://localhost:4200 - Go to "Flow Runs" to see executed flows
- **MLflow UI**: http://localhost:5050 - Go to see model experiments and artifacts

## Troubleshooting

### Flows don't appear in UI
- Make sure you've run the flow at least once
- Check that Prefect server is running: `docker ps | grep prefect`
- Check API URL: `prefect config view | grep PREFECT_API_URL`

### MLflow not accessible
- Check MLflow is running: `docker ps | grep mlflow`
- Verify port: `curl http://localhost:5050`
- Check logs: `docker logs mlflow`

### Worker not picking up flows
- Make sure worker is running: `ps aux | grep "prefect worker"`
- Check work pool exists: `prefect work-pool ls`
- Verify queue name matches deployment

