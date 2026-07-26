"""
RideMatch ingestion ETL: Kafka -> parquet -> MinIO.

Delivery semantics: at-least-once. The consumer has auto-commit disabled and
offsets are committed only after the parquet has been durably uploaded to
MinIO. A crash mid-batch therefore replays the batch rather than silently
dropping events. (The previous version auto-committed on poll, so any failure
between poll and upload lost data with no trace.)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config as BotoConfig
from confluent_kafka import Consumer, KafkaException
from prefect import flow, task

# Make src/ importable regardless of where this is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import KAFKA, S3  # noqa: E402

PREFECT_SERVER_AVAILABLE = os.getenv("PREFECT_API_URL", "").strip() != ""


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3.endpoint_url,
        aws_access_key_id=S3.access_key,
        aws_secret_access_key=S3.secret_key,
        region_name=S3.region,
        config=BotoConfig(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def _consume_kafka_impl(batch_size: int = 100, timeout: float = 1.0):
    """
    Consume up to `batch_size` messages. Returns (messages, consumer).

    The consumer is returned still open so the caller can commit offsets only
    after a successful write. Caller must close it.
    """
    consumer = Consumer(KAFKA.consumer_conf())
    consumer.subscribe([KAFKA.topic])

    msgs = []
    print(f"📥 Consuming up to {batch_size} messages from '{KAFKA.topic}' "
          f"@ {KAFKA.bootstrap_servers} ...")

    empty_polls = 0
    while len(msgs) < batch_size:
        msg = consumer.poll(timeout)
        if msg is None:
            # Tolerate a couple of empty polls: the first poll after a
            # subscribe usually returns None while the group rebalances.
            empty_polls += 1
            if empty_polls >= 3:
                break
            continue
        if msg.error():
            print(f"⚠️  Kafka error: {msg.error()}")
            continue
        empty_polls = 0
        raw = msg.value()
        if not raw:
            continue
        try:
            msgs.append(json.loads(raw))
        except json.JSONDecodeError as e:
            print(f"⚠️  Skipping invalid JSON message: {e}")

    print(f"✅ Consumed {len(msgs)} messages")
    return msgs, consumer


def _write_to_minio_impl(msgs) -> str | None:
    if not msgs:
        print("⚠️  No messages to write")
        return None

    df = pd.DataFrame(msgs)

    # Store timestamps as real tz-aware datetimes. Feast's point-in-time join
    # raises "'str' object has no attribute 'tzinfo'" on string timestamps.
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"])

    if "driver_id" not in df.columns:
        print("⚠️  Batch has no driver_id column — nothing for Feast to ingest.")
        return None

    # Feast driver feature views require a non-empty entity key. Rider-request
    # events carry no driver_id, so they are filtered out here.
    driver_df = df[
        df["driver_id"].notna() & (df["driver_id"].astype(str).str.len() > 0)
    ].copy()

    if driver_df.empty:
        print("⚠️  No driver events in this batch. Nothing to write.")
        return None

    now = datetime.now(timezone.utc)
    fname = f"events_{now.strftime('%Y%m%d_%H%M%S_%f')}.parquet"

    # Write via a temp dir so a failed upload never leaves junk in the repo
    # (the old version wrote into the CWD -- that's why stray .parquet files
    # are sitting in prefect/flows/).
    with tempfile.TemporaryDirectory() as tmp:
        local_path = os.path.join(tmp, fname)
        driver_df.to_parquet(local_path, index=False)

        key = (
            f"{S3.driver_events_prefix}/"
            f"year={now.year}/month={now.month:02d}/day={now.day:02d}/{fname}"
        )
        _s3_client().upload_file(local_path, S3.raw_bucket, key)

    print(f"✅ Uploaded {len(driver_df)} driver events to "
          f"s3://{S3.raw_bucket}/{key}")
    return key


@task(retries=2, retry_delay_seconds=5)
def consume_kafka(batch_size: int = 100, timeout: float = 1.0):
    msgs, consumer = _consume_kafka_impl(batch_size, timeout)
    consumer.close()
    return msgs


@task(retries=3, retry_delay_seconds=5)
def write_to_minio(msgs):
    return _write_to_minio_impl(msgs)


@flow(name="ridematch_ingest")
def ridematch_ingest_flow(batch_size: int = 100):
    msgs = consume_kafka(batch_size)
    return write_to_minio(msgs)


def run_standalone(batch_size: int = 100) -> str | None:
    """Run the ETL without a Prefect server, committing offsets after write."""
    msgs, consumer = _consume_kafka_impl(batch_size)
    try:
        if not msgs:
            return None
        key = _write_to_minio_impl(msgs)
        if key:
            # Commit only now that the data is safely in object storage.
            consumer.commit(asynchronous=False)
            print("✅ Kafka offsets committed")
        else:
            print("↩️  Nothing written — offsets NOT committed, batch will replay.")
        return key
    except KafkaException as e:
        print(f"❌ Kafka commit failed: {e}")
        raise
    finally:
        consumer.close()


if __name__ == "__main__":
    if not PREFECT_SERVER_AVAILABLE:
        print("=" * 60)
        print("⚠️  PREFECT_API_URL unset — running in standalone mode")
        print("=" * 60)
        key = run_standalone()
        print()
        if key:
            print("✅ ETL completed successfully!")
        else:
            print("⚠️  No data processed (topic empty or fully consumed).")
    else:
        ridematch_ingest_flow()
