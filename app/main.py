import logging
import threading
import asyncio
from typing import Optional
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from langgraph.checkpoint.memory import MemorySaver

from app.models.schemas import ScammerInput, ExtractedIntel
from app.engine.graph import build_workflow
from app.core.config import settings
from app.db.repository import db
from app.engine.tools import generate_scam_report, send_guvi_callback

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Global Workflow and MemorySaver
workflow = build_workflow()
memory = MemorySaver()
graph = workflow.compile(checkpointer=memory)

def get_api_key():
    api_key = request.headers.get("x-api-key") or request.args.get("api_key")
    if api_key == settings.API_KEY:
        return api_key
    abort(403, description="Invalid or Missing API Key. Use 'x-api-key' header or 'api_key' query parameter.")

def background_worker(func, *args):
    """Simple background task runner for Flask"""
    thread = threading.Thread(target=func, args=args)
    thread.start()

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "active", "persona_engine": "Multi-Persona (Rajesh, Anjali, Mr. Sharma)"})

@app.route("/syndicate/graph", methods=["GET"])
async def get_syndicate_graph():
    get_api_key()
    links = await db.get_syndicate_links()
    return jsonify(links)

@app.route("/webhook", methods=["POST"])
async def chat_webhook():
    # 1. Auth & Validation
    data = request.get_json()
    if not data:
        abort(400, description="Missing JSON body")
    
    try:
        payload = ScammerInput(**data)
    except Exception as e:
        abort(400, description=f"Invalid payload: {e}")

    effective_api_key = payload.api_key or request.headers.get("x-api-key")
    if effective_api_key != settings.API_KEY:
        abort(403, description="Invalid or Missing API Key")

    try:
        # 2. Process Message
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

        # 3. Invoke Graph - Use MemorySaver for internal state
        # Persistence is handled separately by HoneyDB in the nodes
        config = {"configurable": {"thread_id": payload.session_id}}
        result_state = await graph.ainvoke(initial_state, config=config)

        # 4. Background Tasks
        if payload.generate_report and result_state.get("scam_detected"):
            threading.Thread(target=generate_scam_report, args=(
                result_state["session_id"], 
                result_state["intel"], 
                result_state.get("selected_persona", "RAJESH")
            )).start()

        if result_state.get("scam_detected"):
            background_worker(
                send_guvi_callback,
                result_state["session_id"],
                True,
                result_state.get("turn_count", 1),
                result_state["intel"]
            )

        # 5. RESTful Response
        return jsonify({
            "status": "success",
            "reply": result_state["agent_response"],
            "metadata": {
                "syndicate_score": result_state.get("syndicate_match_score", 0.0),
                "scam_detected": result_state.get("scam_detected", False),
                "turn_count": result_state.get("turn_count", 0)
            }
        })

    except Exception as e:
        logger.error(f"❌ Webhook Critical Error: {e}", exc_info=True)
        abort(500, description="I am experiencing a momentary connection issue.")

@app.route("/admin/report", methods=["GET"])
async def get_summary_report():
    get_api_key()
    stats = await db.get_stats()
    return jsonify({**stats, "status": "Ready for Law Enforcement Export"})

@app.route("/reports/<path:filename>")
def serve_report(filename):
    return send_from_directory(settings.REPORTS_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)