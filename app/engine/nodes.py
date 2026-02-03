import json
from typing import Dict, TypedDict, Any, List
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.core.config import settings
from app.db.repository import db
from app.engine.prompts import RAJESH_SYSTEM_PROMPT, SCAM_DETECTOR_PROMPT
from app.engine.tools import extract_intelligence
from app.models.schemas import ExtractedIntel

# Structured output schema to ensure clean data
class DetectionResult(BaseModel):
    scam_detected: bool = Field(description="Is this a scam?")
    agent_response: str = Field(description="The Rajesh-style response.")

class AgentState(TypedDict):
    session_id: str
    user_message: str
    history: List[Dict[str, str]]
    scam_detected: bool
    agent_response: str
    intel: ExtractedIntel
    turn_count: int

# Initialize LLM with built-in retry logic for 429 errors
llm = ChatGoogleGenerativeAI(
    model="models/gemini-flash-latest",
    google_api_key=settings.GOOGLE_API_KEY,
    temperature=0.7,
    max_retries=5
)

# Bind the schema to the LLM
structured_llm = llm.with_structured_output(DetectionResult)

def load_history(state: AgentState) -> AgentState:
    history = db.get_context(state["session_id"])
    state["history"] = history
    state["turn_count"] = len(history)
    return state

def detect_scam(state: AgentState) -> AgentState:
    """
    Handles detection and response generation in one call for efficiency.
    """
    system_instructions = f"""
    {SCAM_DETECTOR_PROMPT}
    
    If detected as a scam, respond using this persona:
    {RAJESH_SYSTEM_PROMPT}
    
    If NOT a scam, use this exact response: "Hello? Is this Rajesh? I received a message from this number."
    """
    
    messages = [SystemMessage(content=system_instructions)]
    
    # Add history for better context
    for msg in state["history"]:
        role = HumanMessage if msg["role"] == "user" else AIMessage
        messages.append(role(content=msg["content"]))
    
    messages.append(HumanMessage(content=state["user_message"]))
    
    try:
        # Combined call
        result = structured_llm.invoke(messages)
        state["scam_detected"] = result.scam_detected
        state["agent_response"] = result.agent_response
    except Exception as e:
        print(f"API Error: {e}")
        state["scam_detected"] = False
        state["agent_response"] = "Hello? Is this Rajesh?"
        
    return state

def generate_response(state: AgentState) -> AgentState:
    """
    In the new optimized version, the response is already generated in 'detect_scam'.
    This node now simply acts as a pass-through to satisfy your graph structure.
    """
    return state

def extract_intel(state: AgentState) -> AgentState:
    if state["scam_detected"]:
        intel_data = extract_intelligence(state["user_message"])
        state["intel"] = intel_data
    return state

def save_state(state: AgentState) -> AgentState:
    db.add_message(state["session_id"], "user", state["user_message"])
    if state["agent_response"]:
        db.add_message(state["session_id"], "assistant", state["agent_response"])
    state["turn_count"] = db.get_turn_count(state["session_id"])
    return state