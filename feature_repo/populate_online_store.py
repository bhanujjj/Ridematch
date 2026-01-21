#!/usr/bin/env python3
"""
Populate Redis Online Store Directly
====================================

Workaround script that populates Redis online store directly,
bypassing materialization (which has timestamp parsing issues).

Writes directly to Redis using the key format Feast expects.

Usage:
    python populate_online_store.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import random
import json

# Add feature_repo to path
feature_repo_path = Path(__file__).parent
sys.path.insert(0, str(feature_repo_path))

try:
    import minio_config  # noqa: F401
except ImportError:
    pass

from feast import FeatureStore
import redis


def populate_online_store():
    """Populate Redis with sample feature values using direct Redis writes."""
    print("=" * 60)
    print("📦 Populating Redis Online Store")
    print("=" * 60)
    
    # Initialize Feast feature store
    store = FeatureStore(repo_path=str(feature_repo_path))
    
    print(f"📁 Feature repo: {feature_repo_path}")
    print(f"🔗 Online store: Redis (localhost:6379)")
    print()
    
    # Connect to Redis
    try:
        redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        redis_client.ping()
        print("✅ Connected to Redis")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        print("   Make sure Redis is running: docker ps | grep redis")
        sys.exit(1)
    
    # Generate sample data
    print("📊 Generating sample feature data...")
    driver_ids = [f"driver_{i}" for i in range(20)]
    project = store.config.project
    
    print(f"   Generated features for {len(driver_ids)} drivers")
    print()
    
    # Write to Redis using the exact format Feast's RedisOnlineStore expects
    # Based on Feast source code, format is: {project}:{feature_view}:entity:{entity_name}:{entity_value}
    # And values are stored as a hash with feature names as fields
    print("💾 Writing features to Redis...")
    try:
        written_count = 0
        
        for driver_id in driver_ids:
            # Driver status features
            lat_val = 40.7128 + random.uniform(-0.1, 0.1)
            lon_val = -74.0060 + random.uniform(-0.1, 0.1)
            status_val = random.choice(["idle", "on_trip"])
            
            # Feast Redis key format: {project}:{feature_view}:entity:{entity_name}:{entity_value}
            driver_status_key = f"{project}:driver_status:entity:driver_id:{driver_id}"
            
            # Store as hash with feature names as fields (this is what Feast expects)
            redis_client.hset(driver_status_key, mapping={
                "lat": str(lat_val),
                "lon": str(lon_val),
                "status": status_val,
            })
            redis_client.expire(driver_status_key, 300)  # 5 min TTL
            written_count += 1
            
            # Driver agg features
            accept_rate = round(random.uniform(0.5, 0.99), 2)
            response_ms = random.randint(200, 1500)
            
            driver_agg_key = f"{project}:driver_agg:entity:driver_id:{driver_id}"
            redis_client.hset(driver_agg_key, mapping={
                "accept_rate_7d": str(accept_rate),
                "avg_response_ms": str(response_ms),
            })
            redis_client.expire(driver_agg_key, 3600)  # 1 hour TTL
            written_count += 1
        
        print(f"✅ Successfully wrote {written_count} feature sets to Redis")
        print()
        print("📋 Next steps:")
        print("   1. Run: python verify_online_features.py driver_0")
        print("   2. Features are now available for online serving")
        
    except Exception as e:
        print(f"❌ Failed to write to Redis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    populate_online_store()
