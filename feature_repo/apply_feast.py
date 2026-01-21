#!/usr/bin/env python3
"""
Feast Apply Script for MinIO
=============================

This script configures MinIO environment variables and runs feast apply programmatically.
Use this instead of `feast apply` directly to ensure MinIO settings are properly configured.

Why these env vars are required for MinIO:
- AWS_ENDPOINT_URL: Points PyArrow/boto3 to MinIO endpoint (localhost:9000) instead of AWS
- AWS_S3_ADDRESSING_STYLE=path: Forces path-style bucket addressing (required for MinIO)
- ARROW_S3_USE_PATH_STYLE: Tells PyArrow's S3 filesystem to use path-style addressing
- AWS_S3_USE_HTTPS: Set to false since MinIO runs on HTTP locally
- AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY: MinIO credentials (required even for local setup)

Usage:
    python apply_feast.py
    # Or make it executable and run: ./apply_feast.py
"""
import os
import sys

# Set MinIO environment variables before importing Feast
os.environ["AWS_ENDPOINT_URL"] = "http://localhost:9000"
os.environ["AWS_S3_ENDPOINT"] = "http://localhost:9000"
os.environ["AWS_S3_ADDRESSING_STYLE"] = "path"
os.environ["ARROW_S3_USE_PATH_STYLE"] = "true"
os.environ["AWS_S3_USE_HTTPS"] = "false"
os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

# Import minio_config to ensure it's loaded
try:
    import minio_config  # noqa: F401
except ImportError:
    pass

# Now import and run Feast
from feast.repo_operations import apply_total
from feast.repo_config import load_repo_config

def main():
    """Apply Feast feature definitions with MinIO configuration."""
    try:
        # Get the repo path (current directory)
        repo_path = os.path.dirname(os.path.abspath(__file__))
        
        # Load repo config
        repo_config = load_repo_config(repo_path)
        
        # Apply feature definitions
        print("Applying Feast feature definitions...")
        apply_total(repo_config, repo_path)
        print("✅ Successfully applied Feast feature definitions!")
        
    except Exception as e:
        print(f"❌ Error applying Feast definitions: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

