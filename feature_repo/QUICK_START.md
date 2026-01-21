# Feast Online Features - Quick Start

## ✅ What's Already Configured

1. **Redis** - Running in Docker (port 6379)
2. **feature_store.yaml** - Online store configured for Redis
3. **Feature Views** - Both `driver_status` and `driver_agg` have `online=True`
4. **Scripts** - Materialization and verification scripts created

## 🚀 Quick Start Commands

### 1. Start Redis (if not running)

```bash
cd infra
docker-compose up -d redis
```

### 2. Apply Feature Definitions

```bash
cd feature_repo
feast apply
```

### 3. Materialize Features (Populate Redis)

```bash
cd feature_repo

# Set environment variables for MinIO
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_S3_ADDRESSING_STYLE=path
export ARROW_S3_USE_PATH_STYLE=1
export AWS_S3_ENDPOINT=http://localhost:9000
export AWS_ENDPOINT_URL=http://localhost:9000

# Run materialization
python materialize_features.py
```

### 4. Verify Features in Redis

```bash
cd feature_repo
python verify_online_features.py driver_0
```

## 📝 Expected Output

### Materialization Success:
```
✅ Materialization completed successfully!
📊 Features are now available in Redis for online serving
```

### Verification Success:
```
✅ Features retrieved successfully!
📊 Feature Values:
  driver_status:lat          : 40.7128
  driver_status:lon          : -74.0060
  driver_status:status       : idle
  driver_agg:accept_rate_7d  : 0.85
  driver_agg:avg_response_ms : 450
```

## ⚠️ Known Issue: Materialization Timestamp Error

If materialization fails with `'str' object has no attribute 'tzinfo'`:
- This is a Feast 0.56.0 bug with timestamp parsing when reading parquet files
- **Root cause**: Existing parquet files in MinIO have string timestamps instead of datetime objects
- **Workaround**: Use `populate_online_store.py` to write features directly to Redis:
  ```bash
  python populate_online_store.py
  python verify_online_features.py driver_0
  ```
- **Permanent fix**: 
  1. Clear old data:
     ```bash
     docker exec minio mc alias set myminio http://localhost:9000 minioadmin minioadmin
     docker exec minio mc rm --recursive --force myminio/ridematch-raw/
     ```
  2. Re-ingest data (ETL flow now saves proper datetime timestamps)
  3. Materialization will then work correctly

## 🔍 Troubleshooting

**Redis not accessible:**
```bash
docker ps | grep redis
docker-compose restart redis
```

**No features found:**
- Run materialization first: `python materialize_features.py`
- Check offline data exists in MinIO
- Verify feature views: `feast apply`

## 📚 Full Documentation

See `ONLINE_FEATURES_GUIDE.md` for detailed documentation.
