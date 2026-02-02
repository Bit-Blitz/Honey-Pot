import json
from typing import Dict, TypedDict, Any, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.core.config import settings
from app.db.repository import db
from app.engine.prompts import RAJESH_SYSTEM_PROMPT, SCAM_DETECTOR_PROMPT
from app.engine.tools import extract_intelligence
from app.models.schemas import ExtractedIntel

class AgentState(TypedDict):
    session_id: str
    user_message: str
    history: List[Dict[str, str]]
    scam_detected: bool
    agent_response: str
    intel: ExtractedIntel
    turn_count: int

# Initialize Google Gemini
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=settings.GOOGLE_API_KEY,
    temperature=0.7,
    convert_system_message_to_human=True
)

def load_history(state: AgentState) -> AgentState:
    history = db.get_context(state["session_id"])
    state["history"] = history
    state["turn_count"] = len(history)
    return state

def detect_scam(state: AgentState) -> AgentState:
    messages = [
        SystemMessage(content=SCAM_DETECTOR_PROMPT),
        HumanMessage(content=state["user_message"])
    ]
    response = llm.invoke(messages)
    
    try:
        content = response.content.lower()
        state["scam_detected"] = "true" in content
    except:
        state["scam_detected"] = False
    return state

def generate_response(state: AgentState) -> AgentState:
    messages = []
    
    if state["scam_detected"]:
        messages.append(SystemMessage(content=RAJESH_SYSTEM_PROMPT))
        for msg in state["history"]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=state["user_message"]))
        
        response = llm.invoke(messages)
        state["agent_response"] = response.content
    else:
        state["agent_response"] = "Hello? Is this Rajesh? I received a message from this number."
        
    return state

def extract_intel(state: AgentState) -> AgentState:
    intel_data = extract_intelligence(state["user_message"])
    state["intel"] = intel_data
    return state

def save_state(state: AgentState) -> AgentState:
    db.add_message(state["session_id"], "user", state["user_message"])
    if state["agent_response"]:
        db.add_message(state["session_id"], "assistant", state["agent_response"])
    state["turn_count"] = db.get_turn_count(state["session_id"])
    return state