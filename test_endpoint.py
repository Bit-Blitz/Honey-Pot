from fastapi.testclient import TestClient
from app.main import app
import uuid
import httpx

# Setup test client
import httpx
try:
    from fastapi.testclient import TestClient
    client = TestClient(app)
except Exception:
    transport = httpx.ASGITransport(app=app)
    client = httpx.Client(transport=transport, base_url="http://testserver")

# API KEY for authentication
API_KEY = "helware-secret-key-2024"
HEADERS = {"x-api-key": API_KEY}

def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "active"

def test_admin_report_auth():
    # Testing that it works WITH headers
    response = client.get("/admin/report", headers=HEADERS)
    assert response.status_code == 200
    assert "total_sessions" in response.json()

def test_webhook_auth():
    session_id = f"test_{uuid.uuid4().hex[:8]}"
    payload = {
        "sessionId": session_id,
        "message": {
            "sender": "scammer",
            "text": "Hello, I am calling from your bank. Please share your UPI ID.",
            "timestamp": 1770005528731
        },
        "conversationHistory": [],
        "metadata": {
            "channel": "SMS",
            "language": "English",
            "locale": "IN"
        }
    }
    # Testing that it works WITH x-api-key header
    response = client.post("/webhook", json=payload, headers=HEADERS)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "reply" in data
    print(f"   🤖 Agent Reply: {data['reply']}")

if __name__ == "__main__":
    print("🚀 Running API Verification Tests (With Auth)...")
    try:
        test_health_check()
        print("✅ Health Check Passed")
        
        test_admin_report_auth()
        print("✅ Admin Report (With Auth) Passed")
        
        # This one actually calls the LLM
        try:
            test_webhook_auth()
            print("✅ Webhook (With Auth) Passed")
        except Exception as e:
            print(f"❌ Webhook failed: {e}")

        print("\n🎉 All endpoint evaluation readiness tests completed!")
    except AssertionError as e:
        print(f"❌ Test Failed: {e}")
    except Exception as e:
        print(f"💥 Error during testing: {e}")
