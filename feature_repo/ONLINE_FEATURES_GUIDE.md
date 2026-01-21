# Feast Online Features Guide

## Overview

This guide explains how to use Feast's online feature store backed by Redis for low-latency feature serving.

## Architecture

- **Offline Store**: MinIO (S3-compatible) - stores historical features
- **Online Store**: Redis - stores latest feature values for fast retrieval
- **Feature Views**: `driver_status` and `driver_agg` (both enabled for online serving)

## Prerequisites

1. **Redis running**: Redis must be running via Docker
2. **Features materialized**: Features must be materialized from offline → online store
3. **Feature views applied**: Run `feast apply` to register feature definitions

## Setup Instructions

### 1. Start Redis

```bash
cd infra
docker-compose up -d redis
```

Verify Redis is running:
```bash
docker ps | grep redis
```

### 2. Apply Feature Definitions

```bash
cd feature_repo
feast apply
```

This registers your feature views with Feast.

### 3. Materialize Features

Materialize features from offline store (MinIO) to online store (Redis):

```bash
cd feature_repo
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_S3_ADDRESSING_STYLE=path
export ARROW_S3_USE_PATH_STYLE=1
export AWS_S3_ENDPOINT=http://localhost:9000
export AWS_ENDPOINT_URL=http://localhost:9000

python materialize_features.py
```

This will:
- Read latest feature values from MinIO
- Write them to Redis
- Make them available for online serving

### 4. Verify Online Features

Test that features are available in Redis:

```bash
cd feature_repo
python verify_online_features.py driver_0
```

Or test with a different driver:
```bash
python verify_online_features.py driver_5
```

## Usage in Code

### Fetch Online Features

```python
from feast import FeatureStore

store = FeatureStore(repo_path="feature_repo")

# Fetch features for a single driver
features = store.get_online_features(
    features=[
        "driver_status:lat",
        "driver_status:lon",
        "driver_status:status",
        "driver_agg:accept_rate_7d",
        "driver_agg:avg_response_ms",
    ],
    entity_rows=[{"driver_id": "driver_0"}],
)

# Convert to dict
result = features.to_dict()
print(result)
```

### Fetch Features for Multiple Drivers

```python
features = store.get_online_features(
    features=[
        "driver_status:lat",
        "driver_status:lon",
        "driver_agg:accept_rate_7d",
    ],
    entity_rows=[
        {"driver_id": "driver_0"},
        {"driver_id": "driver_1"},
        {"driver_id": "driver_2"},
    ],
)

result = features.to_dict()
# Result is a dict with lists for each feature
# Access: result["driver_status:lat"][0] for first driver
```

## Troubleshooting

### Redis Connection Issues

**Problem**: `Connection refused` or `Unable to connect to Redis`

**Solution**:
```bash
# Check Redis is running
docker ps | grep redis

# Restart Redis
cd infra
docker-compose restart redis
```

### No Features Found

**Problem**: `verify_online_features.py` shows None/empty values

**Solution**:
1. Ensure features are materialized: `python materialize_features.py`
2. Check feature views are applied: `feast apply`
3. Verify offline data exists in MinIO

### Materialization Fails

**Problem**: `materialize_features.py` fails with errors

**Solution**:
1. Check MinIO is running: `docker ps | grep minio`
2. Verify environment variables are set (AWS_ACCESS_KEY_ID, etc.)
3. Check offline data exists: `docker exec minio mc ls minio/ridematch-raw/`

## Redis Data Inspection

If you have `redis-cli` installed:

```bash
# Connect to Redis
redis-cli -h localhost -p 6379

# List all keys (Feast uses prefixed keys)
KEYS *

# Get a specific feature value
GET <feast_key>
```

## Feature TTL (Time To Live)

- **driver_status**: 5 minutes TTL
- **driver_agg**: 1 hour TTL

Features expire after their TTL. Re-run materialization to refresh them.

## Continuous Materialization

For production, set up scheduled materialization:

```bash
# Run every 5 minutes (example using cron)
*/5 * * * * cd /path/to/feature_repo && python materialize_features.py
```

Or use Prefect to schedule materialization runs.

## Configuration Files

- **feature_store.yaml**: Online store configuration (Redis)
- **feature_views.py**: Feature definitions (already set to `online=True`)
- **docker-compose.yml**: Redis service definition

## Summary

1. ✅ Redis is configured in `docker-compose.yml`
2. ✅ Online store is configured in `feature_store.yaml`
3. ✅ Feature views have `online=True`
4. ✅ Materialization script: `materialize_features.py`
5. ✅ Verification script: `verify_online_features.py`

Run materialization → verify → use in your application!
