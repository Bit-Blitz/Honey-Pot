import logging
import time
import os
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from app.models.schemas import ScammerInput, AgentResponse, ExtractedIntel
from app.engine.graph import app_graph
from app.core.config import settings
from app.db.repository import db

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agentic Honey-Pot API", version="1.0.0")

# Serve reports directory as static files
REPORTS_DIR = os.path.join(os.getcwd(), "reports")
if not os.path.exists(REPORTS_DIR):
    os.makedirs(REPORTS_DIR)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# Security
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(header: str = Security(api_key_header)):
    if header == settings.API_KEY:
        return header
    raise HTTPException(status_code=403, detail="Unauthorized: Invalid API Key")

# Simple in-memory cache
response_cache = {}
CACHE_TTL = 60

@app.get("/")
def health_check():
    return {"status": "active", "persona_engine": "Multi-Persona (Rajesh, Anjali, Mr. Sharma)"}

@app.post("/webhook", response_model=AgentResponse)
async def chat_webhook(payload: ScammerInput, api_key: str = Depends(get_api_key)):
    """
    Main webhook for processing scammer messages.
    Now secured with X-API-Key.
    """
    cache_key = f"{payload.session_id}:{payload.message}"
    current_time = time.time()
    
    if cache_key in response_cache:
        cached_res, timestamp = response_cache[cache_key]
        if current_time - timestamp < CACHE_TTL:
            return cached_res
    
    try:
        initial_state = {
            "session_id": payload.session_id,
            "user_message": payload.message,
            "history": [],
            "scam_detected": False,
            "scammer_sentiment": 5,
            "selected_persona": "RAJESH",
            "agent_response": "",
            "intel": ExtractedIntel(),
            "generate_report": payload.generate_report,
            "report_url": None,
            "turn_count": 0
        }

        result_state = app_graph.invoke(initial_state)

        response = AgentResponse(
            session_id=result_state["session_id"],
            scam_detected=result_state["scam_detected"],
            response=result_state["agent_response"],
            extracted_intelligence=result_state["intel"],
            report_url=result_state.get("report_url"),
            metrics={
                "conversation_turns": result_state["turn_count"],
                "scammer_frustration": result_state.get("scammer_sentiment", 5)
            }
        )
        
        response_cache[cache_key] = (response, current_time)
        return response
        
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/admin/report")
async def get_summary_report(api_key: str = Depends(get_api_key)):
    """
    Law Enforcement / Admin View: Summary of all detected scams.
    """
    # This would ideally be a more complex query in repository.py
    # For now, let's just return a placeholder that "does something" with the data
    return {
        "total_sessions": db.get_turn_count("all"), # Just a dummy count for now
        "scams_detected": 42, # Mock data for demo
        "top_upi_ids": ["scammer@okaxis", "fakepay@ybl"],
        "status": "Ready for Law Enforcement Export"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)