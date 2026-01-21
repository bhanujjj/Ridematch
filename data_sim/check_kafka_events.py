#!/usr/bin/env python3
"""
Check Kafka Events
==================

Quick script to check if events are being received in Kafka.

Usage:
    python check_kafka_events.py [num_messages]
"""

import sys
from confluent_kafka import Consumer
import json

def check_events(num_messages=5):
    """Check for events in Kafka topic."""
    consumer = Consumer({
        'bootstrap.servers': 'localhost:9092',
        'group.id': 'event-checker',
        'auto.offset.reset': 'earliest'  # Start from beginning
    })
    
    topic = 'ridematch-events'
    consumer.subscribe([topic])
    
    print(f"📡 Listening for events on topic: {topic}")
    print(f"📊 Fetching up to {num_messages} messages...")
    print("-" * 60)
    
    messages_received = 0
    
    try:
        while messages_received < num_messages:
            msg = consumer.poll(timeout=5.0)
            if msg is None:
                if messages_received == 0:
                    print("❌ No messages found in topic")
                    print("   Make sure generator.py is running and has sent events")
                    break
                else:
                    print(f"\n⚠️  Only received {messages_received} messages (requested {num_messages})")
                    break
            
            if msg.error():
                print(f"❌ Consumer error: {msg.error()}")
                continue
            
            raw_bytes = msg.value()
            if not raw_bytes:
                print("⚠️  Skipping empty message payload")
                continue

            try:
                data = json.loads(raw_bytes.decode("utf-8"))
            except json.JSONDecodeError as e:
                print(f"⚠️  Skipping non-JSON payload: {e}")
                print(f"   Raw: {raw_bytes!r}")
                continue

            messages_received += 1
            
            print(f"\n📨 Message #{messages_received}:")
            print(f"   Event Type: {data.get('event_type', 'unknown')}")
            if 'driver_id' in data:
                print(f"   Driver ID: {data['driver_id']}")
                print(f"   Status: {data.get('status', 'N/A')}")
                print(f"   Location: ({data.get('lat', 0):.4f}, {data.get('lon', 0):.4f})")
            elif 'rider_id' in data:
                print(f"   Rider ID: {data['rider_id']}")
                print(f"   Request ID: {data.get('request_id', 'N/A')}")
            print(f"   Timestamp: {data.get('timestamp', 'N/A')}")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    finally:
        consumer.close()
    
    print("-" * 60)
    print(f"✅ Received {messages_received} messages")

if __name__ == "__main__":
    num_messages = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    check_events(num_messages)
