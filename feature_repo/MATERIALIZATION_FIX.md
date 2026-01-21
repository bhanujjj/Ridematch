# Materialization Timestamp Error - Fix Guide

## Problem

Materialization fails with:
```
AttributeError: 'str' object has no attribute 'tzinfo'
```

This occurs because Feast 0.56.0's Dask offline store expects datetime objects with timezone info, but existing parquet files in MinIO have string timestamps.

## Root Cause

The error happens in Feast's internal code at:
```python
File ".../feast/infra/offline_stores/dask.py", line 704
lambda x: x if x.tzinfo else x.replace(tzinfo=timezone.utc),
```

Feast assumes `x` is a datetime object, but it's receiving strings from parquet files.

## Solutions

### Option 1: Use Workaround Script (Immediate)

Use `populate_online_store.py` to write features directly to Redis:

```bash
cd feature_repo
python populate_online_store.py
python verify_online_features.py driver_0
```

**Note**: This writes sample/test data. For production, use Option 2 or 3.

### Option 2: Re-ingest Data (Recommended)

The ETL flow (`prefect/flows/etl_flow.py`) has been fixed to save proper datetime timestamps:

1. Clear old data from MinIO:
   ```bash
   # First, set up MinIO client alias
   docker exec minio mc alias set myminio http://localhost:9000 minioadmin minioadmin
   
   # Then clear the bucket
   docker exec minio mc rm --recursive --force myminio/ridematch-raw/
   ```

2. Re-run the ETL flow to ingest new data with proper timestamps

3. Materialization will then work correctly:
   ```bash
   python materialize_features.py
   ```

### Option 3: Upgrade Feast (Future)

Upgrade to a newer Feast version that handles timestamp parsing better. However, this may require updating other parts of the codebase.

## Current Status

✅ **Redis online store is configured and working**
✅ **Feature views are set up correctly**
✅ **Verification script can connect to Redis**
⚠️ **Materialization fails due to timestamp format in existing data**
✅ **ETL flow now saves proper datetime timestamps (future data will work)**

## Verification

After using the workaround script or re-ingesting data:

```bash
python verify_online_features.py driver_0
```

Expected output:
```
✅ Features retrieved successfully!
📊 Feature Values:
  driver_status:lat          : 40.7128
  driver_status:lon          : -74.0060
  ...
```

## Next Steps

1. For development/testing: Use `populate_online_store.py`
2. For production: Re-ingest data with proper timestamps
3. Monitor: Check that new data ingested has datetime timestamps (not strings)
