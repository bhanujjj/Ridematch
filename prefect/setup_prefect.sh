#!/bin/bash
# Prefect Setup Script
# This script configures Prefect to use the local server

# Activate conda environment
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook 2>/dev/null)"
    conda activate ridematch 2>/dev/null || echo "Warning: Could not activate ridematch conda environment"
fi

# Set Prefect API URL in the profile
echo "🔧 Configuring Prefect to use local server..."
prefect config set PREFECT_API_URL="http://127.0.0.1:4200/api"

echo "✅ Prefect configuration updated!"
echo "   API URL: http://127.0.0.1:4200/api"
echo ""
echo "📋 Current Prefect configuration:"
prefect config view | grep PREFECT_API_URL

