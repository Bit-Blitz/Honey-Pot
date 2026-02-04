import logging
import time
from fastapi import FastAPI, HTTPException
from app.models.schemas import ScammerInput, AgentResponse, ExtractedIntel
from app.engine.graph import app_graph

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agentic Honey-Pot API", version="1.0.0")

# Simple in-memory cache to prevent redundant processing of the same message
# In production, use Redis or a DB with TTL
response_cache = {}
CACHE_TTL = 60 # 1 minute

@app.get("/")
def health_check():
    return {"status": "active", "persona": "Rajesh", "llm": "Gemini-1.5-Flash"}

@app.post("/webhook", response_model=AgentResponse)
async def chat_webhook(payload: ScammerInput):
    """
    Main webhook for processing scammer messages.
    Includes caching to prevent rate-limit exhaustion from redundant calls.
    """
    cache_key = f"{payload.session_id}:{payload.message}"
    current_time = time.time()
    
    # Check cache
    if cache_key in response_cache:
        cached_res, timestamp = response_cache[cache_key]
        if current_time - timestamp < CACHE_TTL:
            logger.info(f"Returning cached response for session {payload.session_id}")
            return cached_res
    
    try:
        logger.info(f"Processing message for session {payload.session_id}")
        
        # Initialize State
        initial_state = {
            "session_id": payload.session_id,
            "user_message": payload.message,
            "history": [],
            "scam_detected": False,
            "agent_response": "",
            "intel": ExtractedIntel(),
            "turn_count": 0
        }

        # Execute LangGraph Workflow
        result_state = app_graph.invoke(initial_state)

        response = AgentResponse(
            session_id=result_state["session_id"],
            scam_detected=result_state["scam_detected"],
            response=result_state["agent_response"],
            extracted_intelligence=result_state["intel"],
            metrics={
                "conversation_turns": result_state["turn_count"]
            }
        )
        
        # Update cache
        response_cache[cache_key] = (response, current_time)
        
        # Clean up old cache entries occasionally
        if len(response_cache) > 1000:
            logger.info("Cleaning up response cache")
            response_cache.clear() # Simple clear if too big
            
        return response
        
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)