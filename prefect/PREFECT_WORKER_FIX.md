# Prefect Worker Error Fix

## ❌ Error You Were Seeing

```
ValueError: `PREFECT_API_URL` must be set to start a Worker.
```

## ✅ Solution

The Prefect worker needs to know where the Prefect API server is located. We fixed this by:

1. **Setting the PREFECT_API_URL environment variable** to point to your local Prefect server
2. **Creating helper scripts** to make it easy to start the worker

## 🔧 What Was Fixed

### 1. Created `start_worker.sh` Script

This script:
- ✅ Activates the `ridematch` conda environment
- ✅ Sets `PREFECT_API_URL="http://127.0.0.1:4200/api"`
- ✅ Checks if Prefect server is running
- ✅ Starts the worker with the correct configuration

### 2. Created `setup_prefect.sh` Script

This script configures Prefect permanently so you don't need to set the API URL every time.

### 3. Set Prefect Configuration

We set the API URL in your Prefect profile:
```bash
prefect config set PREFECT_API_URL="http://127.0.0.1:4200/api"
```

## 🚀 How to Use

### Option 1: Use the Script (Recommended)

```bash
cd prefect
bash start_worker.sh
```

### Option 2: Manual Setup

```bash
conda activate ridematch
export PREFECT_API_URL="http://127.0.0.1:4200/api"
prefect worker start -q "ridematch-queue" -p "ridematch-pool"
```

## 📋 Prerequisites

1. **Prefect Server Running**: 
   ```bash
   cd infra
   docker-compose up -d prefect
   ```

2. **Verify Server is Running**:
   ```bash
   curl http://127.0.0.1:4200/api/health
   # Should return: true
   ```

## ✅ Verification

After starting the worker, you can verify it's working:

```bash
# Check work pools
conda activate ridematch
PREFECT_API_URL="http://127.0.0.1:4200/api" prefect work-pool ls

# You should see "ridematch-pool" in the list
```

## 🎯 Why This Happened

Prefect workers need to connect to a Prefect API server to:
- Receive work assignments
- Report status updates
- Register themselves with the server

The worker couldn't find the server because `PREFECT_API_URL` wasn't set. Now it's configured to point to your local Prefect server running in Docker on port 4200.

## 📝 Files Created

1. **`prefect/start_worker.sh`** - Script to start the worker with correct configuration
2. **`prefect/setup_prefect.sh`** - Script to configure Prefect (one-time setup)
3. **`prefect/README.md`** - Documentation on how to use the scripts
4. **`prefect/PREFECT_WORKER_FIX.md`** - This file (explanation of the fix)

## 🔍 Technical Details

- **Prefect Server**: Running in Docker on port 4200
- **API URL**: `http://127.0.0.1:4200/api`
- **Worker Queue**: `ridematch-queue`
- **Work Pool**: `ridematch-pool`
- **Conda Environment**: `ridematch`

The fix ensures that when you start a worker, it knows exactly where to find the Prefect API server!

