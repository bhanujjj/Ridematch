"""
Standalone ETL script that consumes Kafka events and writes to MinIO.
This version runs without requiring a Prefect server.
"""
from datetime import datetime
import pandas as pd
import boto3
import json
from confluent_kafka import Consumer
import os

def consume_kafka(batch_size=100, timeout=1):
    """Consume messages from Kafka."""
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
        if msg is None:
            break
        if msg.error():
            continue
        msgs.append(json.loads(msg.value()))
    consumer.close()
    print(f"✅ Consumed {len(msgs)} messages")
    return msgs

def write_to_minio(msgs):
    """Write messages to MinIO as parquet."""
    if not msgs:
        print("⚠️  No messages to write")
        return None
    
    df = pd.DataFrame(msgs)
    # Convert timestamp string to datetime with UTC timezone for proper parquet storage
    # This ensures Feast can read it correctly without timestamp parsing errors
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    fname = f"events_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.parquet"
    df.to_parquet(fname, index=False)
    
    s3 = boto3.client("s3",
                      endpoint_url="http://localhost:9000",
                      aws_access_key_id="minioadmin",
                      aws_secret_access_key="minioadmin")
    
    key = f"year={datetime.utcnow().year}/month={datetime.utcnow().month}/day={datetime.utcnow().day}/{fname}"
    s3.upload_file(fname, "ridematch-raw", key)
    print(f"✅ Uploaded {fname} to MinIO as {key}")
    
    # Clean up local file
    os.remove(fname)
    
    return key

def main():
    """Main ETL function."""
    print("=" * 60)
    print("🔄 RideMatch ETL Pipeline")
    print("=" * 60)
    print()
    
    msgs = consume_kafka()
    key = write_to_minio(msgs)
    
    if key:
        print()
        print("✅ ETL completed successfully!")
        print(f"   Data available in MinIO: s3://ridematch-raw/{key}")
    else:
        print()
        print("⚠️  No data processed (Kafka topic may be empty)")
    
    return key

if __name__ == "__main__":
    main()
