#!/bin/bash
# Prefect Worker Startup Script
# This script sets up the Prefect API URL and starts a worker

# Activate conda environment
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook 2>/dev/null)"
    conda activate ridematch 2>/dev/null || echo "Warning: Could not activate ridematch conda environment"
fi

# Set Prefect API URL (pointing to the Prefect server running in Docker)
# Use 127.0.0.1 instead of localhost for better compatibility
export PREFECT_API_URL="http://127.0.0.1:4200/api"

# Check if Prefect server is running
echo "🔍 Checking Prefect server connection..."
if ! curl -s http://127.0.0.1:4200/api/health > /dev/null 2>&1; then
    echo "❌ Prefect server is not running on http://127.0.0.1:4200"
    echo "   Please start it with:"
    echo "   cd infra && docker-compose up -d prefect"
    echo "   Or start all services:"
    echo "   cd infra && docker-compose up -d"
    exit 1
fi

echo "✅ Prefect server is running at http://127.0.0.1:4200"
echo "🚀 Starting Prefect worker..."
echo "   Queue: ${1:-ridematch-queue}"
echo "   Pool: ${2:-ridematch-pool}"
echo "   API URL: $PREFECT_API_URL"
echo ""

# Start the worker with the provided queue and pool (or defaults)
exec prefect worker start \
    -q "${1:-ridematch-queue}" \
    -p "${2:-ridematch-pool}"

