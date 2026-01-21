# RideMatch Pipeline - Complete Run Guide

## Quick Start Commands

### 1. Start Infrastructure Services
```bash
cd infra
docker-compose up -d
```

Wait ~30 seconds for all services to start, then verify:
```bash
docker ps  # Should show: zookeeper, kafka, redis, minio, mlflow, prefect
```

### 2. Start Data Generator (Terminal 1 - Keep Running)
```bash
cd data_sim
python generator.py
```
**Note**: This runs continuously. Let it run in background or separate terminal.

**To run in background:**
```bash
cd data_sim
python generator.py &
```

**To stop later:**
```bash
pkill -f "python.*generator.py"
```

### 3. Run ETL Flow (Terminal 2 - Run Multiple Times)
```bash
cd prefect/flows
python etl_flow.py
```

**Run this multiple times** to consume batches of events:
```bash
python etl_flow.py  # Batch 1
python etl_flow.py  # Batch 2
python etl_flow.py  # Batch 3
```

**Note**: The ETL flow works even if Prefect server is down (runs in standalone mode).

### 4. Materialize Features to Redis
```bash
cd feature_repo
feast apply
python materialize_features.py
```

### 5. Train Model
```bash
cd src/models
python train_ranking_model.py
```

### 6. Verify Online Features
```bash
cd feature_repo
python verify_online_features.py
```

---

## Troubleshooting

### Prefect Server Not Available?
✅ **No problem!** The ETL flow automatically runs in standalone mode without Prefect server.

### Consumer Group Already Consumed Messages?
If ETL shows "0 messages consumed", the consumer group has already read them. Options:

**Option 1**: Use a different consumer group (change `group.id` in `etl_flow.py`)

**Option 2**: Reset consumer group offset:
```bash
# Delete the consumer group
docker exec kafka kafka-consumer-groups --bootstrap-server localhost:9092 --delete --group ridematch-consumer
```

**Option 3**: Wait for generator to send more messages, then run ETL again

### Check Kafka Messages
```bash
# Check if messages are in Kafka (using Python)
python -c "
from confluent_kafka import Consumer
c = Consumer({'bootstrap.servers': 'localhost:9092', 'group.id': 'test-reader', 'auto.offset.reset': 'earliest'})
c.subscribe(['ridematch-events'])
msg = c.poll(5)
if msg:
    print('✅ Messages available:', msg.value()[:100])
else:
    print('⚠️  No messages available')
c.close()
"
```

### Check MinIO Data
```bash
# List files in MinIO
docker exec minio mc ls myminio/ridematch-raw/ --recursive
```

---

## Complete Pipeline Sequence

```bash
# Terminal 1: Start generator (runs continuously)
cd data_sim && python generator.py

# Terminal 2: Run ETL multiple times
cd prefect/flows
python etl_flow.py  # Wait 10-20 seconds between runs
python etl_flow.py
python etl_flow.py

# Terminal 2: Materialize and train
cd ../../feature_repo
feast apply
python materialize_features.py

cd ../src/models
python train_ranking_model.py
```

---

## Expected Outputs

1. **Generator**: `📊 Batch #X: Sent Y events | Delivered: Z | Total: W`
2. **ETL Flow**: `✅ Consumed X messages` → `✅ Uploaded events_*.parquet to MinIO`
3. **Materialization**: `✅ Materialization completed successfully!`
4. **Training**: `✅ Model logged to MLflow` → `✅ Model registered as 'ridematch-ranker'`
