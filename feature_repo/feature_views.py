# Configure MinIO settings before importing Feast components
# This ensures PyArrow uses the correct endpoint and path-style addressing
import minio_config  # noqa: F401 - Imported for side effects (env var setup)

from datetime import timedelta

from feast import FeatureView, Field
from feast.types import Float32, String
from feast.infra.offline_stores.file_source import FileSource
from feast.data_format import ParquetFormat        # ✅ new import for Feast ≥0.40
from entities import driver                         # ✅ absolute import

# ------------------------------------------------------------------------------
# 1️⃣  Offline Source (MinIO or local S3-compatible bucket)
# ------------------------------------------------------------------------------
# 
# Why MinIO configuration is required:
# - s3_endpoint_override: Points PyArrow to MinIO endpoint (localhost:9000) instead of AWS
# - Environment variables (set in minio_config.py): Configure credentials, path-style addressing, and HTTP
#   - AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY: MinIO credentials
#   - ARROW_S3_USE_PATH_STYLE: Path-style addressing (required for MinIO, not virtual-hosted style)
#   - AWS_S3_USE_HTTPS: Set to false since MinIO runs on HTTP locally
#   Path-style: s3.amazonaws.com/bucket/key vs Virtual-hosted: bucket.s3.amazonaws.com/key
#
# The minio_config module (imported above) automatically sets all required environment variables
# so Feast can read from s3://ridematch-raw/ without manual exports each time.

driver_events = FileSource(
    path="s3://ridematch-raw/driver_events/",       # only driver events (must include driver_id)
    timestamp_field="timestamp",
    file_format=ParquetFormat(),                    # ✅ must use ParquetFormat()
    s3_endpoint_override="http://localhost:9000",   # MinIO endpoint (required for PyArrow)
)

# ------------------------------------------------------------------------------
# 2️⃣  Low-latency driver status features
# ------------------------------------------------------------------------------

driver_status_fv = FeatureView(
    name="driver_status",
    entities=[driver],
    ttl=timedelta(minutes=5),
    schema=[
        Field(name="lat", dtype=Float32),
        Field(name="lon", dtype=Float32),
        Field(name="status", dtype=String),
    ],
    source=driver_events,
    online=True,
)

# ------------------------------------------------------------------------------
# 3️⃣  Aggregated driver-level metrics
# ------------------------------------------------------------------------------

driver_agg_fv = FeatureView(
    name="driver_agg",
    entities=[driver],
    ttl=timedelta(hours=1),
    schema=[
        Field(name="accept_rate_7d", dtype=Float32),
        Field(name="avg_response_ms", dtype=Float32),
    ],
    source=driver_events,
    online=True,
)
