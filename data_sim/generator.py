import json, random, time, uuid
from datetime import datetime, timezone
from confluent_kafka import Producer
import sys

BROKER = "localhost:9092"

# Track delivery callbacks
delivered_count = 0

def delivery_callback(err, msg):
    """Callback to track message delivery status."""
    global delivered_count
    if err:
        print(f"❌ Message delivery failed: {err}")
    else:
        delivered_count += 1

# Initialize producer with retry logic
def get_producer(max_retries=5, retry_delay=2):
    """Get Kafka producer with retry logic for connection issues."""
    for attempt in range(max_retries):
        try:
            producer = Producer({
                "bootstrap.servers": BROKER,
                "socket.timeout.ms": 60000,  # 60 seconds
                "message.timeout.ms": 30000,  # 30 seconds
                "delivery.timeout.ms": 30000,  # 30 seconds
                "request.timeout.ms": 30000,   # 30 seconds
                "enable.idempotence": False,  # Disable idempotence for simpler config
                "acks": 1,  # Wait for leader acknowledgment
            })
            # Wait for metadata to be available (ensures topic exists)
            print("   Waiting for Kafka metadata...")
            producer.poll(1)
            time.sleep(1)  # Give Kafka time to fetch metadata
            return producer
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"⚠️  Kafka connection attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                raise ConnectionError(f"Failed to connect to Kafka after {max_retries} attempts: {e}")
    return None

# Initialize producer lazily - will connect when main() is called
p = None

def random_coord(center=(40.7128, -74.0060), spread=0.02):
    return center[0] + random.uniform(-spread, spread), center[1] + random.uniform(-spread, spread)

def driver_event(driver_id):
    lat, lon = random_coord()
    return {
        "event_type": "driver_update",
        "driver_id": driver_id,
        "lat": lat,
        "lon": lon,
        "status": random.choice(["idle", "on_trip"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "accept_rate_7d": round(random.uniform(0.5, 0.99), 2),
        "avg_response_ms": random.randint(200, 1500)
    }

def rider_request(rider_id):
    origin = random_coord()
    dest = random_coord()
    return {
        "event_type": "rider_request",
        "request_id": str(uuid.uuid4()),
        "rider_id": rider_id,
        "origin": origin,
        "dest": dest,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pref_vehicle": random.choice(["sedan", "suv"])
    }

def main():
    global p
    
    # Initialize producer on first run
    if p is None:
        print("🚀 Starting RideMatch data generator...")
        print(f"📡 Connecting to Kafka at {BROKER}...")
        p = get_producer()
        print("✅ Connected to Kafka!")
    
    drivers = [f"driver_{i}" for i in range(100)]
    riders = [f"rider_{i}" for i in range(200)]
    topic = "ridematch-events"
    
    print(f"📨 Sending events to topic: {topic}")
    print("✅ Generating events...\n")
    
    event_count = 0
    batch_num = 0
    
    while True:
        try:
            batch_num += 1
            batch_count = 0
            batch_start = delivered_count
            
            # Send driver events
            for d in random.sample(drivers, 10):
                p.produce(
                    topic, 
                    json.dumps(driver_event(d)).encode("utf-8"),
                    callback=delivery_callback
                )
                batch_count += 1
            
            # Send rider request (30% chance)
            if random.random() < 0.3:
                r = random.choice(riders)
                p.produce(
                    topic, 
                    json.dumps(rider_request(r)).encode("utf-8"),
                    callback=delivery_callback
                )
                batch_count += 1
            
            # Poll to process delivery callbacks
            p.poll(0.1)
            
            # Flush to ensure delivery (with longer timeout)
            remaining = p.flush(timeout=10)
            delivered_in_batch = delivered_count - batch_start
            event_count += delivered_in_batch
            
            # Print status every batch (so you can see it's working)
            if batch_num <= 5 or batch_num % 10 == 0:
                print(f"📊 Batch #{batch_num}: Sent {batch_count} events | Delivered: {delivered_in_batch} | Total: {event_count} | Pending: {remaining if remaining else 0}")
            
            time.sleep(1)
        except Exception as e:
            print(f"❌ Error sending message: {e}")
            print("   Retrying connection...")
            p = get_producer()
            time.sleep(1)

if __name__ == "__main__":
    main()
