#!/usr/bin/env python3
"""
Feast Feature Materialization Script
====================================

Materializes features from offline store (MinIO) to online store (Redis).
This populates Redis with the latest feature values for online serving.

Usage:
    python materialize_features.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add feature_repo to path
feature_repo_path = Path(__file__).parent
sys.path.insert(0, str(feature_repo_path))

# Configure MinIO environment variables
try:
    import minio_config  # noqa: F401
except ImportError:
    os.environ.update({
        "AWS_ENDPOINT_URL": "http://localhost:9000",
        "AWS_S3_ENDPOINT": "http://localhost:9000",
        "AWS_S3_ADDRESSING_STYLE": "path",
        "ARROW_S3_USE_PATH_STYLE": "1",
        "AWS_S3_USE_HTTPS": "0",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
        "AWS_REGION": "us-east-1",
    })

from feast import FeatureStore


def materialize_features():
    """Materialize features from offline store to Redis online store."""
    print("=" * 60)
    print("🔄 Feast Feature Materialization")
    print("=" * 60)
    
    # Initialize Feast feature store
    store = FeatureStore(repo_path=str(feature_repo_path))
    
    print(f"📁 Feature repo: {feature_repo_path}")
    print(f"🔗 Online store: Redis (localhost:6379)")
    print()
    
    # Materialize features up to now
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=1)  # Last 24 hours
    
    print(f"📅 Materializing features from {start_date} to {end_date}")
    print()
    
    try:
        # Try materialize() with explicit date range first
        # This may handle timestamp issues better than materialize_incremental()
        print("Attempting materialization with date range...")
        store.materialize(start_date=start_date, end_date=end_date)
        print("✅ Materialization completed successfully!")
        print()
        print("📊 Features are now available in Redis for online serving")
        print("   Use get_online_features() to retrieve them")
        
    except Exception as e:
        error_msg = str(e)
        if "'str' object has no attribute 'tzinfo'" in error_msg:
            print(f"⚠️  Materialization failed due to timestamp parsing issue in Feast 0.56.0")
            print()
            print("This is a known issue with Feast when reading parquet files with string timestamps.")
            print()
            print("Workaround options:")
            print("1. Use populate_online_store.py to write features directly to Redis:")
            print("   python populate_online_store.py")
            print()
            print("2. Re-ingest data with proper datetime timestamps (already fixed in etl_flow.py)")
            print("   New data will work correctly with materialization")
            print()
            print("3. Clear old parquet files from MinIO and re-ingest:")
            print("   docker exec minio mc rm --recursive --force minio/ridematch-raw/")
            print()
            sys.exit(1)
        else:
            print(f"❌ Materialization failed: {e}")
            print()
            print("Troubleshooting:")
            print("1. Check Redis is running: docker ps | grep redis")
            print("2. Check Redis connection")
            print("3. Verify feature views are applied: feast apply")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    materialize_features()
