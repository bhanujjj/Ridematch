"""
Central configuration for RideMatch.

Every endpoint and credential is read from the environment with a
local-development default. Nothing is hardcoded at a call site, so the exact
same code runs on the host (localhost:9092) and inside a container
(kafka:29092) with no edits -- only env vars change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    val = os.getenv(key)
    return val if val not in (None, "") else default


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str = field(default_factory=lambda: _env("S3_ENDPOINT_URL", "http://localhost:9000"))
    access_key: str = field(default_factory=lambda: _env("AWS_ACCESS_KEY_ID", "minioadmin"))
    secret_key: str = field(default_factory=lambda: _env("AWS_SECRET_ACCESS_KEY", "minioadmin"))
    region: str = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    raw_bucket: str = field(default_factory=lambda: _env("RIDEMATCH_RAW_BUCKET", "ridematch-raw"))
    driver_events_prefix: str = field(
        default_factory=lambda: _env("RIDEMATCH_DRIVER_EVENTS_PREFIX", "driver_events")
    )

    @property
    def use_ssl(self) -> bool:
        return self.endpoint_url.startswith("https://")

    @property
    def driver_events_uri(self) -> str:
        return f"s3://{self.raw_bucket}/{self.driver_events_prefix}/"

    def pandas_storage_options(self) -> dict:
        """storage_options for pandas/fsspec reads against MinIO."""
        return {
            "key": self.access_key,
            "secret": self.secret_key,
            "client_kwargs": {"endpoint_url": self.endpoint_url},
            "config_kwargs": {"s3": {"addressing_style": "path"}},
            "use_ssl": self.use_ssl,
        }

    def export_env(self) -> None:
        """
        Push settings into os.environ.

        PyArrow's S3 filesystem and the Feast CLI are configured purely through
        env vars, and Feast constructs the filesystem internally where we cannot
        pass arguments -- so this has to happen before Feast is imported.
        """
        os.environ.setdefault("AWS_ACCESS_KEY_ID", self.access_key)
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", self.secret_key)
        os.environ.setdefault("AWS_REGION", self.region)
        os.environ.setdefault("AWS_DEFAULT_REGION", self.region)
        os.environ.setdefault("AWS_ENDPOINT_URL", self.endpoint_url)
        os.environ.setdefault("AWS_S3_ENDPOINT", self.endpoint_url)
        # MinIO only speaks path-style addressing.
        os.environ.setdefault("AWS_S3_ADDRESSING_STYLE", "path")
        os.environ.setdefault("ARROW_S3_USE_PATH_STYLE", "1")
        os.environ.setdefault("AWS_S3_USE_HTTPS", "1" if self.use_ssl else "0")


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str = field(
        default_factory=lambda: _env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    )
    topic: str = field(default_factory=lambda: _env("KAFKA_TOPIC", "ridematch-events"))
    consumer_group: str = field(
        default_factory=lambda: _env("KAFKA_CONSUMER_GROUP", "ridematch-consumer")
    )

    def consumer_conf(self) -> dict:
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.consumer_group,
            "auto.offset.reset": _env("KAFKA_AUTO_OFFSET_RESET", "earliest"),
            # Commit only after a batch is durably written to MinIO, so a crash
            # mid-ETL replays the batch instead of silently dropping it.
            "enable.auto.commit": False,
        }

    def producer_conf(self) -> dict:
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "linger.ms": int(_env("KAFKA_LINGER_MS", "20")),
            "compression.type": _env("KAFKA_COMPRESSION", "lz4"),
            "acks": _env("KAFKA_ACKS", "all"),
        }


@dataclass(frozen=True)
class ServiceConfig:
    redis_host: str = field(default_factory=lambda: _env("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(_env("REDIS_PORT", "6379")))
    mlflow_tracking_uri: str = field(
        default_factory=lambda: _env("MLFLOW_TRACKING_URI", "http://localhost:5050")
    )
    model_name: str = field(default_factory=lambda: _env("RIDEMATCH_MODEL_NAME", "ridematch-ranker"))
    api_port: int = field(default_factory=lambda: int(_env("API_PORT", "8000")))
    candidate_pool_size: int = field(
        default_factory=lambda: int(_env("RIDEMATCH_CANDIDATE_POOL", "100"))
    )

    def export_env(self) -> None:
        """
        Push REDIS_HOST/REDIS_PORT into os.environ.

        feature_store.yaml's online_store.connection_string reads these via
        Feast's `${VAR}` expansion (os.path.expandvars), so they must be set
        before Feast parses that file -- same reasoning as S3Config.export_env.
        """
        os.environ.setdefault("REDIS_HOST", self.redis_host)
        os.environ.setdefault("REDIS_PORT", str(self.redis_port))


S3 = S3Config()
KAFKA = KafkaConfig()
SERVICES = ServiceConfig()
