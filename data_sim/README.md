# RideMatch Data Generator

## Overview

This directory contains the data generator that creates synthetic driver and rider events and sends them to Kafka.

## Files

- **`generator.py`** - Main generator script that sends events to Kafka
- **`check_kafka_events.py`** - Utility to check events in Kafka topic

## How It Works

### Event Flow

```
generator.py → Kafka Topic (ridematch-events) → ETL Flow → MinIO → Feast
```

1. **Generator** (`generator.py`) continuously generates events:
   - ~10 driver update events per second
   - ~30% chance of rider request events
   - Sends to Kafka topic `ridematch-events`

2. **Kafka** stores events in topic until consumed

3. **ETL Flow** (`prefect/flows/etl_flow.py`) consumes events and saves to MinIO

4. **MinIO** stores parquet files for Feast offline store

## Usage

### Generate Events

```bash
cd data_sim
python generator.py
```

The generator runs in an **infinite loop** - it's not stuck! It will:
- Show connection status
- Display progress every 10 batches
- Continue until you press `Ctrl+C`

**Example output:**
```
🚀 Starting RideMatch data generator...
📡 Connecting to Kafka at localhost:9092...
✅ Connected to Kafka!
📨 Sending events to topic: ridematch-events
✅ Generating events...

📊 Batch #1: Sent 10 events | Delivered: 10 | Total: 10 | Pending: 0
📊 Batch #2: Sent 11 events | Delivered: 11 | Total: 21 | Pending: 0
...
```

### Check Events in Kafka

```bash
# Check for events in Kafka topic
python check_kafka_events.py [num_messages]

# Example: Get 5 messages
python check_kafka_events.py 5
```

### Consume Events with ETL Flow

```bash
# Run ETL flow to consume events and save to MinIO
cd ../prefect/flows
python etl_flow.py
```

## Where Events Are Stored

1. **Kafka Topic**: `ridematch-events`
   - Events are queued here until consumed
   - Location: Kafka broker at `localhost:9092`
   - Use `check_kafka_events.py` to view them

2. **MinIO** (after ETL processing):
   - Bucket: `ridematch-raw`
   - Format: Parquet files with partitioned paths
   - Used by Feast for offline feature store

3. **Redis** (after materialization):
   - Latest feature values for online serving
   - Use `feature_repo/verify_online_features.py` to check

## Troubleshooting

### Generator Shows "Generating events..." But No Output

This is **normal**! The generator:
- Runs in an infinite loop (`while True`)
- Only prints progress every 10 batches
- Is actively sending events (check with `check_kafka_events.py`)

### No Events in Kafka

1. Check Kafka is running:
   ```bash
   docker ps | grep kafka
   ```

2. Check topic exists:
   ```bash
   docker exec kafka kafka-topics.sh --list --bootstrap-server localhost:9092
   ```

3. Verify generator is connected:
   - Look for "✅ Connected to Kafka!" message
   - Check for any error messages

4. Test with check script:
   ```bash
   python check_kafka_events.py 1
   ```

### Generator Connection Errors

If you see connection errors:
- The generator has automatic retry logic (5 attempts)
- Wait a few seconds for Kafka to be ready
- Check Kafka logs: `docker logs kafka`

## Event Types

### Driver Update Event
```json
{
  "event_type": "driver_update",
  "driver_id": "driver_0",
  "lat": 40.7128,
  "lon": -74.0060,
  "status": "idle",
  "timestamp": "2025-01-19T18:00:00Z",
  "accept_rate_7d": 0.85,
  "avg_response_ms": 500
}
```

### Rider Request Event
```json
{
  "event_type": "rider_request",
  "request_id": "uuid-here",
  "rider_id": "rider_0",
  "origin": [40.7128, -74.0060],
  "dest": [40.7580, -73.9855],
  "timestamp": "2025-01-19T18:00:00Z",
  "pref_vehicle": "sedan"
}
```

## Next Steps

1. Run generator: `python generator.py`
2. Check events: `python check_kafka_events.py`
3. Run ETL flow to save to MinIO
4. Materialize features to Redis
5. Train model with features
