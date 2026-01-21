import requests
import json
import time

def test_match_api():
    url = "http://localhost:8000/match"
    payload = {
        "rider_id": "rider_test",
        "rider_lat": 40.7306,
        "rider_lon": -73.9352,
        "top_k": 3
    }
    
    print(f"📡 Sending request to {url}...")
    print(f"📦 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        data = response.json()
        print("\n✅ Response received:")
        print(json.dumps(data, indent=2))
        
        if not data["matches"]:
            print("\n⚠️  No matches returned. Ensure features are materialized and model is available.")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ Could not connect to server. Is it running?")
        print("   Run: uvicorn src.match_api.main:app --port 8000")
    except Exception as e:
        print(f"\n❌ Request failed: {e}")
        if 'response' in locals():
            print(f"   Status: {response.status_code}")
            print(f"   Body: {response.text}")

if __name__ == "__main__":
    test_match_api()
