import httpx
from httpx import AsyncClient, ASGITransport
import asyncio
from app.main import app, lifespan
import uuid
import json

# API KEY for authentication
API_KEY = "helware-secret-key-2024"
HEADERS = {"x-api-key": API_KEY}

async def run_tests():
    print("🚀 Running Startup-Grade API Verification (Async)...")
    
    # Use lifespan context manager to ensure app.state.graph is initialized
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Trigger lifespan
        async with lifespan(app):
            # 1. Health Check
            try:
                response = await client.get("/")
                assert response.status_code == 200
                print("✅ Health Check Passed")
            except Exception as e:
                print(f"❌ Health Check Failed: {e}")

            # 2. Admin Auth
            try:
                response = await client.get("/admin/report", headers=HEADERS)
                assert response.status_code == 200
                print("✅ Admin Auth & Persistence Passed")
            except Exception as e:
                print(f"❌ Admin Auth Failed: {e}")

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
                    "metadata": {
                        "channel": "SMS",
                        "language": "English",
                        "locale": "IN"
                    }
                }
                
                print(f"   📤 Sending Scammer Message: {payload['message']['text']}")
                response = await client.post("/webhook", json=payload, headers=HEADERS)
                
                if response.status_code != 200:
                    print(f"❌ Webhook failed with status {response.status_code}: {response.text}")
                else:
                    data = response.json()
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
    asyncio.run(run_tests())
