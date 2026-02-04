import logging
import time
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.models.schemas import ScammerInput, AgentResponse, ExtractedIntel
from app.engine.graph import build_workflow
from app.core.config import settings
from app.db.repository import db
from app.engine.tools import generate_scam_report, send_guvi_callback
from app.api import ws

# Setup rate limiter
limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the lifecycle of the Agentic Graph and its persistent checkpointer.
    """
    # Initialize the persistent async checkpointer
    # LangGraph AsyncSqliteSaver.from_conn_string returns a context manager
    async with AsyncSqliteSaver.from_conn_string(settings.CHECKPOINT_DB_PATH) as saver:
        workflow = build_workflow()
        # Compile the graph with the checkpointer
        app.state.graph = workflow.compile(checkpointer=saver)
        logger.info(f"🚀 Agentic Graph Compiled with Async Checkpointer at {settings.CHECKPOINT_DB_PATH}")
        yield
    # Saver automatically closes here due to context manager

app = FastAPI(
    title="Agentic Honey-Pot API", 
    version="1.0.0",
    lifespan=lifespan
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Authentication scheme - Hackathon uses x-api-key
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == settings.API_KEY:
        return api_key
    raise HTTPException(
        status_code=403, detail="Invalid or Missing API Key"
    )

# Include WebSocket and other routers
app.include_router(ws.router)

# Setup logging
from pythonjsonlogger import jsonlogger
logger = logging.getLogger(__name__)

# Serve reports directory as static files
REPORTS_DIR = settings.REPORTS_DIR
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# Background Task for PDF generation (Solving the Sync Bottleneck)
def generate_async_report(session_id: str, intel: ExtractedIntel, persona: str):
    try:
        filename = generate_scam_report(session_id, intel, persona)
        logger.info(f"Background Report Generated: {filename}", extra={"session_id": session_id})
        # In production, you'd update a DB record or send a webhook here
    except Exception as e:
        logger.error(f"Background Report Error: {e}")

@app.get("/")
def health_check():
    return {"status": "active", "persona_engine": "Multi-Persona (Rajesh, Anjali, Mr. Sharma)"}

@app.get("/syndicate/graph", dependencies=[Depends(get_api_key)])
async def get_syndicate_graph():
    """
    Returns a graph representation of linked scam sessions.
    Used for the Syndicate Intelligence dashboard.
    """
    return await db.get_syndicate_links()

@app.post("/webhook", response_model=AgentResponse, dependencies=[Depends(get_api_key)])
@limiter.limit("5/minute")
async def chat_webhook(
    request: Request, 
    payload: ScammerInput, 
    background_tasks: BackgroundTasks
):
    """
    Main webhook for processing scammer messages.
    Secured with Rate Limiting.
    Now fully async to prevent worker blocking.
    """
    try:
        # Check if graph is initialized
        if not hasattr(app.state, "graph"):
             logger.error("Agentic Graph not initialized in lifespan. Check startup logs.")
             # For tests where lifespan might not run correctly, we attempt to initialize it without saver
             # but this is not recommended for production
             workflow = build_workflow()
             app.state.graph = workflow.compile()

        # Convert incoming conversation history to AgentState format
        history = []
        for msg in payload.conversation_history:
            role = "user" if msg.sender == "scammer" else "assistant"
            history.append({"role": role, "content": msg.text})

        initial_state = {
            "session_id": payload.session_id,
            "user_message": payload.message.text,
            "history": history,
            "scam_detected": False,
            "high_priority": False,
            "scammer_sentiment": 5,
            "selected_persona": "RAJESH",
            "agent_response": "",
            "intel": ExtractedIntel(),
            "is_returning_scammer": False,
            "syndicate_match_score": 0.0,
            "generate_report": payload.generate_report,
            "human_intervention": payload.human_intervention,
            "report_url": None,
            "turn_count": len(history)
        }

        # Invoke Graph with Checkpointing (thread_id) - ASYNC
        config = {"configurable": {"thread_id": payload.session_id}}
        result_state = await request.app.state.graph.ainvoke(initial_state, config=config)

        # Trigger Background Report if requested
        if payload.generate_report and result_state.get("scam_detected"):
            background_tasks.add_task(
                generate_async_report, 
                result_state["session_id"], 
                result_state["intel"], 
                result_state.get("selected_persona", "RAJESH")
            )

        # MANDATORY GUVI CALLBACK
        # Trigger if scam detected and we have some engagement (turn_count > 0)
        if result_state.get("scam_detected"):
            background_tasks.add_task(
                send_guvi_callback,
                result_state["session_id"],
                True,
                result_state.get("turn_count", 1),
                result_state["intel"]
            )

        # Syndicate Alert (Honeypot Callback)
        if result_state.get("is_returning_scammer"):
            await ws.manager.broadcast({
                "type": "syndicate_alert",
                "session_id": result_state["session_id"],
                "match_score": result_state.get("syndicate_match_score")
            })

        # Hackathon mandated response format with extra intelligence metadata
        return AgentResponse(
            status="success",
            reply=result_state["agent_response"],
            metadata={
                "syndicate_score": result_state.get("syndicate_match_score", 0.0),
                "scam_detected": result_state.get("scam_detected", False),
                "turn_count": result_state.get("turn_count", 0)
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ Webhook Critical Error: {e}", exc_info=True)
        # Return a structured error response instead of just 500
        return AgentResponse(
            status="error",
            reply="I am experiencing a momentary connection issue. Please bear with me."
        )

@app.get("/admin/report", dependencies=[Depends(get_api_key)])
async def get_summary_report():
    """
    Law Enforcement / Admin View: Summary of all detected scams.
    """
    stats = await db.get_stats()
    return {
        **stats,
        "status": "Ready for Law Enforcement Export"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)