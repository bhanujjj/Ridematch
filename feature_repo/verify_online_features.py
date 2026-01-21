#!/usr/bin/env python3
"""
Feast Online Features Verification Script
=========================================

Verifies that features are available in Redis online store.

Usage:
    python verify_online_features.py [driver_id]
    
Example:
    python verify_online_features.py driver_0
"""

import os
import sys
from pathlib import Path

# Add feature_repo to path
feature_repo_path = Path(__file__).parent
sys.path.insert(0, str(feature_repo_path))

# Configure MinIO environment variables (if needed)
try:
    import minio_config  # noqa: F401
except ImportError:
    pass

from feast import FeatureStore


def verify_online_features(driver_id: str = "driver_0"):
    """Verify online features are available in Redis."""
    print("=" * 60)
    print("🔍 Feast Online Features Verification")
    print("=" * 60)
    
    # Initialize Feast feature store
    try:
        store = FeatureStore(repo_path=str(feature_repo_path))
        print(f"✅ Feature store initialized")
    except Exception as e:
        print(f"❌ Failed to initialize feature store: {e}")
        sys.exit(1)
    
    print(f"📁 Feature repo: {feature_repo_path}")
    print(f"🔗 Online store: Redis (localhost:6379)")
    print(f"👤 Driver ID: {driver_id}")
    print()
    
    # Fetch online features
    try:
        print("📥 Fetching online features...")
        features = store.get_online_features(
            features=[
                "driver_status:lat",
                "driver_status:lon",
                "driver_status:status",
                "driver_agg:accept_rate_7d",
                "driver_agg:avg_response_ms",
            ],
            entity_rows=[{"driver_id": driver_id}],
        )
        
        # Convert to dict for easier display
        result = features.to_dict()
        
        print("✅ Features retrieved successfully!")
        print()
        print("📊 Feature Values:")
        print("-" * 60)
        for key, value in result.items():
            # Handle list values (Feast returns lists)
            if isinstance(value, list) and len(value) > 0:
                val = value[0]
            else:
                val = value
            
            # Format display
            if isinstance(val, float):
                print(f"  {key:30s}: {val:.4f}")
            else:
                print(f"  {key:30s}: {val}")
        
        print("-" * 60)
        print()
        
        # Check if features have values
        has_values = any(
            (isinstance(v, list) and len(v) > 0 and v[0] is not None) or 
            (not isinstance(v, list) and v is not None)
            for v in result.values()
        )
        
        if has_values:
            print("✅ Features are populated in Redis!")
        else:
            print("⚠️  Features retrieved but values are None/empty")
            print("   Run materialization first: python materialize_features.py")
        
    except Exception as e:
        print(f"❌ Failed to fetch online features: {e}")
        print()
        print("Troubleshooting:")
        print("1. Check Redis is running: docker ps | grep redis")
        print("2. Check Redis connection: redis-cli ping")
        print("3. Materialize features first: python materialize_features.py")
        print("4. Verify feature views: feast apply")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    driver_id = sys.argv[1] if len(sys.argv) > 1 else "driver_0"
    verify_online_features(driver_id)
