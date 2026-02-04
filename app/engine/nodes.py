import json
import logging
from typing import Dict, TypedDict, Any, List
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.db.repository import db
from app.engine.prompts import RAJESH_SYSTEM_PROMPT, SCAM_DETECTOR_PROMPT
from app.engine.tools import extract_intelligence
from app.models.schemas import ExtractedIntel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Initialize LLM
llm = ChatGoogleGenerativeAI(
    model="models/gemini-1.5-flash", # Updated to a more stable model name
    google_api_key=settings.GOOGLE_API_KEY,
    temperature=0.7,
    max_retries=3 # Reduced as we'll use tenacity for better control
)

# Bind the schema to the LLM
structured_llm = llm.with_structured_output(DetectionResult)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception), # We can narrow this down if we know the specific API error type
    reraise=True
)
def _call_llm_with_retry(messages):
    return structured_llm.invoke(messages)

def load_history(state: AgentState) -> AgentState:
    try:
        history = db.get_context(state["session_id"])
        state["history"] = history
        state["turn_count"] = len(history)
        # Load persistent scam flag
        state["scam_detected"] = db.is_scam_session(state["session_id"])
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        state["history"] = []
        state["turn_count"] = 0
        state["scam_detected"] = False
    return state

def detect_scam(state: AgentState) -> AgentState:
    """
    Handles detection and response generation in one call for efficiency.
    If already detected as a scam in previous turns, it skips re-detection.
    """
    
    # If already detected as a scam, we only need to generate a persona response
    if state.get("scam_detected"):
        system_instructions = RAJESH_SYSTEM_PROMPT
    else:
        system_instructions = f"""
        {SCAM_DETECTOR_PROMPT}
        
        If detected as a scam, respond using this persona:
        {RAJESH_SYSTEM_PROMPT}
        
        If NOT a scam, use this exact response: "Hello? Is this Rajesh? I received a message from this number."
        """
    
    messages = [SystemMessage(content=system_instructions)]
    
    # Add history for better context (limit to last 5 turns to save tokens and avoid rate limits)
    for msg in state["history"][-5:]:
        role = HumanMessage if msg["role"] == "user" else AIMessage
        messages.append(role(content=msg["content"]))
    
    messages.append(HumanMessage(content=state["user_message"]))
    
    try:
        logger.info(f"Calling LLM for session {state['session_id']} (Previously detected: {state.get('scam_detected')})")
        
        # If already detected, we don't need structured output for is_scam, 
        # but for consistency we use the same structured_llm.
        # Alternatively, we could use a simpler LLM call if already detected.
        # Let's stick to structured_llm to keep the output schema consistent.
        
        result = _call_llm_with_retry(messages)
        
        # Once scam_detected is True, it stays True
        if not state.get("scam_detected"):
            state["scam_detected"] = result.scam_detected
            
        state["agent_response"] = result.agent_response
    except Exception as e:
        logger.error(f"API Error after retries: {e}")
        # Fallback response
        if state.get("scam_detected"):
            state["agent_response"] = "Beta, are you there? My internet is very slow today."
        else:
            state["agent_response"] = "Hello? Is this Rajesh? My signal is weak, can you repeat?"
        
    return state

def extract_intel(state: AgentState) -> AgentState:
    try:
        if state["scam_detected"]:
            intel_data = extract_intelligence(state["user_message"])
            state["intel"] = intel_data
    except Exception as e:
        logger.error(f"Error extracting intelligence: {e}")
    return state

def save_state(state: AgentState) -> AgentState:
    try:
        db.add_message(state["session_id"], "user", state["user_message"])
        if state["agent_response"]:
            db.add_message(state["session_id"], "assistant", state["agent_response"])
        
        # Persist scam flag if it was newly detected or already set
        if state.get("scam_detected"):
            db.set_scam_flag(state["session_id"], True)
            
        state["turn_count"] = db.get_turn_count(state["session_id"])
    except Exception as e:
        logger.error(f"Error saving state: {e}")
    return state