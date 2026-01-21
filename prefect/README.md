# Prefect Worker Setup

## Problem

When starting a Prefect worker, you may encounter this error:
```
ValueError: `PREFECT_API_URL` must be set to start a Worker.
```

This happens because the worker needs to know where the Prefect API server is located.

## Solution

We have two scripts to help you:

### 1. `setup_prefect.sh` - Configure Prefect (One-time setup)

This script sets the Prefect API URL in your Prefect profile so it persists across sessions.

```bash
cd prefect
bash setup_prefect.sh
```

This sets `PREFECT_API_URL="http://127.0.0.1:4200/api"` in your Prefect configuration.

### 2. `start_worker.sh` - Start the Worker

This script:
- Checks if the Prefect server is running
- Sets the API URL environment variable
- Starts the Prefect worker

**Usage:**
```bash
cd prefect
bash start_worker.sh [queue-name] [pool-name]
```

**Examples:**
```bash
# Use default queue and pool
bash start_worker.sh

# Specify custom queue and pool
bash start_worker.sh my-queue my-pool

# Use the defaults (ridematch-queue, ridematch-pool)
bash start_worker.sh ridematch-queue ridematch-pool
```

## Prerequisites

1. **Prefect Server Running**: The Prefect server must be running in Docker
   ```bash
   cd infra
   docker-compose up -d prefect
   ```

2. **Conda Environment**: The `ridematch` conda environment must be activated (the script does this automatically)

3. **Prefect Installed**: Prefect should be installed in your conda environment

## How It Works

1. The script activates the `ridematch` conda environment
2. Sets `PREFECT_API_URL="http://127.0.0.1:4200/api"` (points to Prefect server in Docker)
3. Checks if the Prefect server is accessible
4. Starts the worker with the specified queue and pool

## Manual Setup (Alternative)

If you prefer to set it up manually:

```bash
# Activate conda environment
conda activate ridematch

# Set API URL
export PREFECT_API_URL="http://127.0.0.1:4200/api"

# Start worker
prefect worker start -q "ridematch-queue" -p "ridematch-pool"
```

Or set it in your Prefect profile (persists across sessions):
```bash
prefect config set PREFECT_API_URL="http://127.0.0.1:4200/api"
```

## Troubleshooting

### Worker can't connect to server
- Check if Prefect server is running: `docker ps | grep prefect`
- Check if server is accessible: `curl http://127.0.0.1:4200/api/health`
- Start the server: `cd infra && docker-compose up -d prefect`

### Wrong API URL
- Verify the Prefect server port (should be 4200)
- Check your docker-compose.yml configuration
- Use `prefect config view` to see current configuration

### Conda environment issues
- Make sure the `ridematch` environment exists
- Activate it manually: `conda activate ridematch`
- Verify Prefect is installed: `prefect version`

## Quick Start

```bash
# 1. Start Prefect server (if not already running)
cd infra
docker-compose up -d prefect

# 2. Configure Prefect (one-time setup)
cd ../prefect
bash setup_prefect.sh

# 3. Start the worker
bash start_worker.sh
```

That's it! Your worker should now be running and ready to process flows from the `ridematch-queue`.

