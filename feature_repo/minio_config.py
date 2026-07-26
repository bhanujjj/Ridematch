"""
MinIO/S3 environment setup for Feast.

Imported for its side effects by feature_views.py and the training/materialize
scripts. Feast constructs its PyArrow S3 filesystem internally, so the only way
to point it at MinIO is via environment variables set *before* Feast imports.

The actual values live in src/config.py -- this module is just the shim that
applies them, so there is a single source of truth for endpoints/credentials.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import S3

# Push AWS_*/ARROW_* vars into os.environ for PyArrow, boto3 and the Feast CLI.
S3.export_env()

# Kept as module-level names because existing scripts import them.
MINIO_ENDPOINT = S3.endpoint_url
MINIO_ACCESS_KEY = S3.access_key
MINIO_SECRET_KEY = S3.secret_key


def setup_minio_env() -> None:
    """Re-apply the environment. Idempotent; kept for backwards compatibility."""
    S3.export_env()
