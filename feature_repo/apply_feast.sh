#!/bin/bash
# Feast Apply Wrapper for MinIO
# This script activates the conda environment, sets up MinIO configuration, and runs feast apply

# Activate conda environment (if conda is available)
if command -v conda &> /dev/null; then
    # Initialize conda if not already initialized
    eval "$(conda shell.bash hook 2>/dev/null)"
    conda activate ridematch 2>/dev/null || echo "Warning: Could not activate ridematch conda environment"
fi

# Change to feature_repo directory
cd "$(dirname "$0")"

# Run feast apply (minio_config.py will automatically set up MinIO environment variables)
feast apply

