from prefect import flow, task
from datetime import datetime, timezone
import pandas as pd, boto3, json, os
from confluent_kafka import Consumer

# Check if Prefect server is available, otherwise run without it
# This allows the flow to work even if Prefect server is down
PREFECT_SERVER_AVAILABLE = os.getenv("PREFECT_API_URL", "").strip() != ""

def _consume_kafka_impl(batch_size=100, timeout=1):
    """Internal implementation of Kafka consumption."""
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "ridematch-consumer",
        "auto.offset.reset": "earliest"
    })
    consumer.subscribe(["ridematch-events"])
    msgs = []
    print(f"📥 Consuming up to {batch_size} messages from Kafka...")
    while len(msgs) < batch_size:
        msg = consumer.poll(timeout)
        if msg is None: break
        if msg.error(): continue
        try:
            value = msg.value()
            if value:  # Only process non-empty messages
                msgs.append(json.loads(value))
        except json.JSONDecodeError as e:
            print(f"⚠️  Skipping invalid JSON message: {e}")
            continue
    consumer.close()
    print(f"✅ Consumed {len(msgs)} messages")
    return msgs

@task
def consume_kafka(batch_size=100, timeout=1):
    return _consume_kafka_impl(batch_size, timeout)

def _write_to_minio_impl(msgs):
    """Internal implementation of MinIO write."""
    if not msgs:
        print("⚠️  No messages to write")
        return None
    df = pd.DataFrame(msgs)
    # Convert timestamp string to datetime with UTC timezone for proper parquet storage
    # This ensures Feast can read it correctly without timestamp parsing errors
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    # Split: Feast driver feature views require non-empty driver_id rows.
    # Rider requests do NOT have driver_id, so we store driver events separately.
    now = datetime.now(timezone.utc)
    fname = f"events_{now.strftime('%Y%m%d_%H%M%S')}.parquet"

    driver_df = df[df.get("driver_id").notna() & (df.get("driver_id").astype(str).str.len() > 0)].copy()
    if driver_df.empty:
        print("⚠️  No driver events found in this batch (no non-empty driver_id). Nothing to write for Feast.")
        return None

    driver_df.to_parquet(fname, index=False)
    s3 = boto3.client("s3",
                      endpoint_url="http://localhost:9000",
                      aws_access_key_id="minioadmin",
                      aws_secret_access_key="minioadmin")
    key = f"driver_events/year={now.year}/month={now.month}/day={now.day}/{fname}"
    s3.upload_file(fname, "ridematch-raw", key)
    print(f"✅ Uploaded {fname} to MinIO as {key}")
    # Clean up local file
    if os.path.exists(fname):
        os.remove(fname)
    return key

@task
def write_to_minio(msgs):
    return _write_to_minio_impl(msgs)

@flow(name="ridematch_ingest")
def ridematch_ingest_flow():
    msgs = consume_kafka()
    key = write_to_minio(msgs)
    return key

if __name__ == "__main__":
    # If Prefect server is not available, run the functions directly
    # This is a fallback when Prefect server is down
    if not PREFECT_SERVER_AVAILABLE:
        print("=" * 60)
        print("⚠️  Prefect server not available, running in standalone mode...")
        print("=" * 60)
        print()
        msgs = _consume_kafka_impl()  # Call the function directly without Prefect
        key = _write_to_minio_impl(msgs)  # Call the function directly without Prefect
        if key:
            print()
            print("✅ ETL completed successfully!")
        else:
            print()
            print("⚠️  No data processed (Kafka topic may be empty or already consumed)")
    else:
        ridematch_ingest_flow()
