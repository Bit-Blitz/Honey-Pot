from fastapi import FastAPI
from app.models.schemas import ScammerInput, AgentResponse, ExtractedIntel
from app.engine.graph import app_graph

app = FastAPI(title="Agentic Honey-Pot API", version="1.0.0")

@app.get("/")
def health_check():
    return {"status": "active", "persona": "Rajesh", "llm": "Gemini-1.5-Flash"}

@app.post("/webhook", response_model=AgentResponse)
async def chat_webhook(payload: ScammerInput):
    """
    Main webhook for processing scammer messages.
    No Authentication required for Hackathon demo.
    """
    
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

    return AgentResponse(
        session_id=result_state["session_id"],
        scam_detected=result_state["scam_detected"],
        response=result_state["agent_response"],
        extracted_intelligence=result_state["intel"],
        metrics={
            "conversation_turns": result_state["turn_count"]
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)