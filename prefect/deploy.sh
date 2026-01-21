#!/bin/bash
# Deploy Prefect Flows using CLI
# This script deploys flows using Prefect CLI commands

# Activate conda environment
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook 2>/dev/null)"
    conda activate ridematch 2>/dev/null || echo "Warning: Could not activate ridematch conda environment"
fi

# Set Prefect API URL
export PREFECT_API_URL="http://127.0.0.1:4200/api"

# Change to project root
cd "$(dirname "$0")/.."

echo "🚀 Deploying Prefect flows..."
echo "   API URL: $PREFECT_API_URL"
echo ""

# Deploy flows using prefect deploy command
# This requires deployment YAML files, but for now we'll use flow.serve() approach
# which is better for local development

echo "📦 To deploy flows, you have two options:"
echo ""
echo "Option 1: Use flow.serve() for local development (recommended)"
echo "   This allows flows to be discovered and run directly"
echo ""
echo "Option 2: Create deployment YAML files and use 'prefect deploy'"
echo ""
echo "For now, flows can be run directly with:"
echo "   python prefect/flows/etl_flow.py"
echo "   python prefect/flows/train_flow.py"
echo ""
echo "To see flows in the UI, they need to be run at least once,"
echo "or you can use flow.serve() to make them available."

