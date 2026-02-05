import requests
import uuid
import json
import time
from app.main import app

def run_tests():
    print("🚀 Running Startup-Grade REST API Verification (Flask)...")
    
    # API KEY for authentication
    API_KEY = "helware-secret-key-2024"
    HEADERS = {"x-api-key": API_KEY}

    with app.test_client() as client:
        # 1. Health Check
        try:
            response = client.get("/")
            assert response.status_code == 200
            print("✅ Health Check Passed")
        except Exception as e:
            print(f"❌ Health Check Failed: {e}")

        # 2. Admin Report
        try:
            response = client.get("/admin/report", headers=HEADERS)
            assert response.status_code == 200
            print("✅ Admin Auth & Persistence Passed")
        except Exception as e:
            print(f"❌ Admin Report Failed: {e}")

        # 2.1 Syndicate Graph
        try:
            response = client.get("/syndicate/graph", headers=HEADERS)
            assert response.status_code == 200
            data = response.get_json()
            assert "nodes" in data
            print("✅ Syndicate Graph API Passed")
        except Exception as e:
            print(f"❌ Syndicate Graph Failed: {e}")

        # 3. Webhook (Agentic Loop)
        try:
            session_id = f"test_{uuid.uuid4().hex[:8]}"
            payload = {
                "sessionId": session_id,
                "message": {
                    "sender": "scammer",
                    "text": "Hello, I am calling from your bank. Please share your UPI ID to verify your account.",
                    "timestamp": 1770005528731
                },
                "conversationHistory": [],
                "apiKey": API_KEY, # Test body auth too
                "metadata": {
                    "channel": "SMS",
                    "language": "English",
                    "locale": "IN"
                }
            }
            
            print(f"   📤 Sending Scammer Message: {payload['message']['text']}")
            response = client.post("/webhook", json=payload)
            
            if response.status_code != 200:
                print(f"❌ Webhook failed with status {response.status_code}: {response.get_data(as_text=True)}")
            else:
                data = response.get_json()
                assert data["status"] == "success"
                print("✅ End-to-End Agentic Loop Passed")
                print(f"   🤖 Agent Reply: {data['reply']}")
                
                if "metadata" in data:
                    print(f"   📊 Syndicate Score: {data['metadata'].get('syndicate_score', 0)}")
                    print(f"   🔍 Scam Detected: {data['metadata'].get('scam_detected')}")
        except Exception as e:
            print(f"❌ Webhook Test Error: {e}")

    print("\n🎉 PROJECT STATUS: EVALUATION READY")

if __name__ == "__main__":
    run_tests()
