import json
import logging
from typing import Dict, TypedDict, Any, List, Optional
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
from app.engine.prompts import (
    RAJESH_SYSTEM_PROMPT, 
    ANJALI_SYSTEM_PROMPT, 
    MR_SHARMA_SYSTEM_PROMPT,
    SCAM_DETECTOR_PROMPT,
    INTEL_EXTRACTOR_PROMPT
)
from app.engine.tools import extract_intelligence, generate_scam_report
from app.models.schemas import ExtractedIntel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Structured output schema for detection
class DetectionResult(BaseModel):
    scam_detected: bool = Field(description="Is this a scam?")
    scammer_sentiment: int = Field(description="Frustration level 1-10")
    selected_persona: str = Field(description="RAJESH, ANJALI, or MR_SHARMA")
    agent_response: str = Field(description="The persona-style response.")

# Structured output schema for intel extraction
class IntelResult(BaseModel):
    upi_ids: List[str] = []
    bank_details: List[str] = []
    phishing_links: List[str] = []
    phone_numbers: List[str] = []

class AgentState(TypedDict):
    session_id: str
    user_message: str
    history: List[Dict[str, str]]
    scam_detected: bool
    scammer_sentiment: int
    selected_persona: str
    agent_response: str
    intel: ExtractedIntel
    generate_report: bool
    report_url: Optional[str]
    turn_count: int

# Initialize LLMs
llm = ChatGoogleGenerativeAI(
    model="models/gemini-1.5-flash",
    google_api_key=settings.GOOGLE_API_KEY,
    temperature=0.7,
    max_retries=3
)

structured_detector = llm.with_structured_output(DetectionResult)
structured_extractor = llm.with_structured_output(IntelResult)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def _call_detector(messages):
    return structured_detector.invoke(messages)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def _call_extractor(messages):
    return structured_extractor.invoke(messages)

def load_history(state: AgentState) -> AgentState:
    try:
        history = db.get_context(state["session_id"])
        state["history"] = history
        state["turn_count"] = len(history)
        state["scam_detected"] = db.is_scam_session(state["session_id"])
        # We could also load the last persona used from DB if we added it
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        state["history"] = []
        state["turn_count"] = 0
        state["scam_detected"] = False
    return state

def finalize_report(state: AgentState) -> AgentState:
    """
    Generates the PDF report if the user requested it and intel exists.
    """
    if state.get("generate_report") and state.get("scam_detected"):
        try:
            filename = generate_scam_report(
                state["session_id"], 
                state["intel"], 
                state.get("selected_persona", "RAJESH")
            )
            state["report_url"] = f"/reports/{filename}"
            logger.info(f"Report generated: {filename}")
        except Exception as e:
            logger.error(f"Report Generation Error: {e}")
            state["report_url"] = None
    else:
        state["report_url"] = None
        
    return state

def detect_scam(state: AgentState) -> AgentState:
    """
    Handles detection, sentiment analysis, and response generation.
    """
    persona_prompts = {
        "RAJESH": RAJESH_SYSTEM_PROMPT,
        "ANJALI": ANJALI_SYSTEM_PROMPT,
        "MR_SHARMA": MR_SHARMA_SYSTEM_PROMPT
    }
    
    current_persona_prompt = persona_prompts.get(state.get("selected_persona", "RAJESH"), RAJESH_SYSTEM_PROMPT)
    
    system_instructions = f"""
    {SCAM_DETECTOR_PROMPT}
    
    --- PERSONA DATA ---
    RAJESH: {RAJESH_SYSTEM_PROMPT}
    ANJALI: {ANJALI_SYSTEM_PROMPT}
    MR_SHARMA: {MR_SHARMA_SYSTEM_PROMPT}
    
    If already in a scam session, continue with the current persona: {state.get('selected_persona', 'RAJESH')}
    """

    if state.get("scam_detected"):
        # If we already have a persona locked, stick with it but let the detector know
        current_persona = state.get("selected_persona", "RAJESH")
        system_instructions += f"\nSTAY IN PERSONA: {current_persona}. DO NOT SWITCH."
    else:
        system_instructions += "\nSELECT THE BEST PERSONA to start with based on the scammer's first message."
    
    messages = [SystemMessage(content=system_instructions)]
    for msg in state["history"][-5:]:
        role = HumanMessage if msg["role"] == "user" else AIMessage
        messages.append(role(content=msg["content"]))
    messages.append(HumanMessage(content=state["user_message"]))
    
    try:
        result = _call_detector(messages)
        if not state.get("scam_detected"):
            state["scam_detected"] = result.scam_detected
            
        state["scammer_sentiment"] = result.scammer_sentiment
        state["selected_persona"] = result.selected_persona
        state["agent_response"] = result.agent_response
    except Exception as e:
        logger.error(f"Detector Error: {e}")
        state["agent_response"] = "Hello? I am having some trouble with my phone..."
        
    return state

def extract_intel(state: AgentState) -> AgentState:
    """
    Upgraded LLM-based extraction to catch obfuscated details.
    """
    if not state["scam_detected"]:
        return state

    try:
        # 1. Use Regex as a fast first pass
        regex_intel = extract_intelligence(state["user_message"])
        
        # 2. Use LLM for deeper forensics
        messages = [
            SystemMessage(content=INTEL_EXTRACTOR_PROMPT),
            HumanMessage(content=f"EXTRACT FROM THIS MESSAGE: {state['user_message']}")
        ]
        llm_result = _call_extractor(messages)
        
        # Merge results
        merged_upi = list(set(regex_intel.upi_ids + llm_result.upi_ids))
        merged_bank = list(set(regex_intel.bank_details + llm_result.bank_details))
        merged_links = list(set(regex_intel.phishing_links + llm_result.phishing_links))
        
        state["intel"] = ExtractedIntel(
            upi_ids=merged_upi,
            bank_details=merged_bank,
            phishing_links=merged_links
        )
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
    return state

def save_state(state: AgentState) -> AgentState:
    try:
        db.add_message(state["session_id"], "user", state["user_message"])
        if state["agent_response"]:
            db.add_message(state["session_id"], "assistant", state["agent_response"])
        
        if state.get("scam_detected"):
            db.set_scam_flag(state["session_id"], True)
            # Log sentiment for metrics
            logger.info(f"Session {state['session_id']} Sentiment: {state['scammer_sentiment']}")
            
        state["turn_count"] = db.get_turn_count(state["session_id"])
    except Exception as e:
        logger.error(f"Error saving state: {e}")
    return state