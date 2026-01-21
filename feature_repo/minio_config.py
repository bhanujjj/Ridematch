"""
MinIO Configuration for Feast
=============================

This module configures PyArrow and boto3 to work with MinIO (local S3-compatible storage)
by setting the required environment variables and S3 configuration.

Why these env vars are required for MinIO:
- AWS_ENDPOINT_URL: Points PyArrow/boto3 to MinIO endpoint (localhost:9000) instead of AWS
- AWS_S3_ADDRESSING_STYLE=path: Forces path-style bucket addressing (bucket.s3.amazonaws.com vs s3.amazonaws.com/bucket)
  MinIO requires path-style addressing, not virtual-hosted style
- ARROW_S3_USE_PATH_STYLE: Tells PyArrow's S3 filesystem to use path-style addressing
- AWS_S3_USE_HTTPS: Set to false since MinIO runs on HTTP locally
- AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY: MinIO credentials (required even for local setup)

This configuration ensures Feast's CLI can read from s3://ridematch-raw/ without manual exports.
"""
import os

# MinIO connection settings
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

def setup_minio_env():
    """Configure environment variables for MinIO access via PyArrow/boto3."""
    # Set MinIO endpoint (PyArrow reads this)
    os.environ["AWS_ENDPOINT_URL"] = MINIO_ENDPOINT
    os.environ["AWS_S3_ENDPOINT"] = MINIO_ENDPOINT
    
    # Force path-style addressing (required for MinIO)
    os.environ["AWS_S3_ADDRESSING_STYLE"] = "path"
    os.environ["ARROW_S3_USE_PATH_STYLE"] = "1"  # Use "1" instead of "true" for some PyArrow versions
    
    # Use HTTP (not HTTPS) for local MinIO
    os.environ["AWS_S3_USE_HTTPS"] = "0"  # Use "0" instead of "false"
    
    # Set MinIO credentials
    os.environ["AWS_ACCESS_KEY_ID"] = MINIO_ACCESS_KEY
    os.environ["AWS_SECRET_ACCESS_KEY"] = MINIO_SECRET_KEY
    
    # Additional PyArrow S3 settings
    os.environ["AWS_REGION"] = "us-east-1"  # Required but ignored by MinIO
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    
    # Configure boto3 default session (PyArrow might use this)
    try:
        import boto3
        from botocore.config import Config
        
        # Create a custom config for path-style addressing
        s3_config = Config(
            s3={
                'addressing_style': 'path',
                'use_ssl': False,
            },
            signature_version='s3v4',
        )
        
        # Set up boto3 default session with MinIO endpoint
        boto3.setup_default_session(
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name='us-east-1',
        )
        
        # Also configure boto3 client defaults
        boto3.DEFAULT_SESSION = boto3.Session(
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name='us-east-1',
        )
        
    except ImportError:
        # boto3 not available
        pass

# Automatically configure MinIO when this module is imported
setup_minio_env()

# Monkey-patch PyArrow's S3FileSystem if possible
try:
    import pyarrow.fs as pafs
    
    # Store original S3FileSystem for reference
    _original_s3_filesystem = pafs.S3FileSystem
    
    def _create_minio_s3_filesystem(*args, **kwargs):
        """Create S3FileSystem with MinIO configuration."""
        # Extract endpoint from environment or use default
        endpoint = os.environ.get("AWS_ENDPOINT_URL", MINIO_ENDPOINT)
        # Remove protocol for endpoint_override
        endpoint_override = endpoint.replace("http://", "").replace("https://", "")
        
        # Merge MinIO config with any provided kwargs
        minio_kwargs = {
            "access_key": MINIO_ACCESS_KEY,
            "secret_key": MINIO_SECRET_KEY,
            "endpoint_override": endpoint_override,
            "scheme": "http",
            "region": "us-east-1",
        }
        minio_kwargs.update(kwargs)
        
        return _original_s3_filesystem(*args, **minio_kwargs)
    
    # Note: We can't easily monkey-patch PyArrow's internal S3 filesystem creation
    # because Feast creates it internally. Environment variables should be sufficient.
    
except ImportError:
    # PyArrow not available, but env vars should still work
    pass

