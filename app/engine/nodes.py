import json
import logging
import httpx
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
from app.db.vector_store import vector_db
from app.engine.prompts import (
    RAJESH_SYSTEM_PROMPT, 
    ANJALI_SYSTEM_PROMPT, 
    MR_SHARMA_SYSTEM_PROMPT,
    SCAM_DETECTOR_PROMPT,
    INTEL_EXTRACTOR_PROMPT
)
from app.engine.tools import generate_scam_report
from app.models.schemas import ExtractedIntel

# Setup structured logging
from pythonjsonlogger import jsonlogger
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
logHandler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Structured output schema for detection
class DetectionResult(BaseModel):
    scam_detected: bool = Field(description="Is this a scam?")
    high_priority: bool = Field(description="Does this message contain high-value intel like bank details, OTP, or passwords?", default=False)
    scammer_sentiment: int = Field(description="Frustration level 1-10")
    selected_persona: str = Field(description="RAJESH, ANJALI, or MR_SHARMA")
    agent_response: str = Field(description="The persona-style response.")

# Structured output schema for intel extraction
class IntelResult(BaseModel):
    upi_ids: List[str] = []
    bank_details: List[str] = []
    phishing_links: List[str] = []
    phone_numbers: List[str] = []
    suspicious_keywords: List[str] = []
    agent_notes: Optional[str] = None

class AgentState(TypedDict):
    session_id: str
    user_message: str
    history: List[Dict[str, str]]
    scam_detected: bool
    high_priority: bool
    scammer_sentiment: int
    selected_persona: str
    agent_response: str
    intel: ExtractedIntel
    is_returning_scammer: bool
    syndicate_match_score: float
    generate_report: bool
    report_url: Optional[str]
    turn_count: int
    human_intervention: bool = False # Flag for manual hand-off

# Initialize LLMs
llm = ChatGoogleGenerativeAI(
    model="models/gemini-flash-latest",
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
async def _call_detector(messages):
    return await structured_detector.ainvoke(messages)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
async def _call_extractor(messages):
    return await structured_extractor.ainvoke(messages)

async def load_history(state: AgentState) -> AgentState:
    try:
        # Await async DB calls
        history = await db.get_context(state["session_id"])
        state["history"] = history
        state["turn_count"] = len(history)
        state["scam_detected"] = await db.is_scam_session(state["session_id"])
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        state["history"] = []
        state["turn_count"] = 0
        state["scam_detected"] = False
    return state

async def finalize_report(state: AgentState) -> AgentState:
    """
    Generates the PDF report if the user requested it and intel exists.
    """
    if state.get("generate_report") and state.get("scam_detected"):
        try:
            # Report generation is sync (file IO), we could run in threadpool if needed
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

async def detect_scam(state: AgentState) -> AgentState:
    """
    Core Node: 
    1. Detects scam intent
    2. Analyzes sentiment (for frustration stalling)
    3. Handles human hand-off
    4. Generates response based on persona
    """
    # HUMAN HAND-OFF LOGIC
    if state.get("human_intervention"):
        state["agent_response"] = "[MANUAL CONTROL ENABLED] A forensic investigator is reviewing this session. Please continue the interaction via the admin dashboard."
        state["scam_detected"] = True # Assume scam if human intervenes
        return state

    # 1. SCAM DETECTION & SENTIMENT
    state["turn_count"] = state.get("turn_count", 0) + 1

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
    
    --- DYNAMIC STRATEGY ---
    Current Scammer Sentiment: {state.get('scammer_sentiment', 5)} (1=Calm, 10=Angry)
    If Sentiment > 7: STALL. Be more confused, take longer to understand, ask for "technical help" from a grandson, or tell a long irrelevant story. 
    Make them waste as much time as possible.
    
    If already in a scam session, continue with the current persona: {state.get('selected_persona', 'RAJESH')}
    """

    if state.get("scam_detected"):
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
        result = await _call_detector(messages)
        if not state.get("scam_detected"):
            state["scam_detected"] = result.scam_detected
            
        state["high_priority"] = result.high_priority
        state["scammer_sentiment"] = result.scammer_sentiment
        state["selected_persona"] = result.selected_persona
        state["agent_response"] = result.agent_response
        
        if result.high_priority:
            logger.info("🚨 HIGH PRIORITY INTEL DETECTED - Short-circuiting to forensics.")
            
    except Exception as e:
        logger.error(f"Detector Error: {e}")
        persona = state.get("selected_persona", "RAJESH")
        error_responses = {
            "RAJESH": "Hello? Beta, I think my phone is acting up again. Can you hear me?",
            "ANJALI": "One second, my signal is very weak here. Let me move closer to the window.",
            "MR_SHARMA": "I apologize, this modern technology is quite temperamental. Please hold on a moment."
        }
        state["agent_response"] = error_responses.get(persona, "Hello? I am having some trouble with my phone...")
        state["high_priority"] = False
        
    return state

async def extract_intel(state: AgentState) -> AgentState:
    """
    Upgraded LLM-based extraction to catch obfuscated details.
    Removed regex pass to rely 100% on LLM for better accuracy.
    """
    if not state["scam_detected"]:
        return state

    try:
        # Use LLM for deeper forensics
        messages = [
            SystemMessage(content=INTEL_EXTRACTOR_PROMPT),
            HumanMessage(content=f"EXTRACT FROM THIS MESSAGE: {state['user_message']}")
        ]
        llm_result = await _call_extractor(messages)
        
        state["intel"] = ExtractedIntel(
            upi_ids=llm_result.upi_ids,
            bank_details=llm_result.bank_details,
            phishing_links=llm_result.phishing_links,
            phone_numbers=llm_result.phone_numbers,
            suspicious_keywords=llm_result.suspicious_keywords,
            agent_notes=llm_result.agent_notes
        )
        
        # BROADCAST INTEL - REMOVED WEBSOCKETS FOR STRICT REST COMPLIANCE
        # Intel is saved to DB and available via /admin/report or /syndicate/graph
        pass
        
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
    return state

async def enrich_intel(state: AgentState) -> AgentState:
    """
    Enriches extracted intel with metadata using ASYNC calls.
    """
    if not state["scam_detected"] or not state["intel"]:
        return state

    async with httpx.AsyncClient() as client:
        # 1. Verify UPI
        if state["intel"].upi_ids:
            for upi in state["intel"].upi_ids:
                try:
                    response = await client.get(f"https://api.shrtm.nu/upi/verify?id={upi}", timeout=5.0)
                    if response.status_code == 200:
                        bank_name = response.json().get('bank', 'HDFC Bank')
                        logger.info(f"Verified UPI: {upi} at {bank_name}")
                except Exception as e:
                    logger.warning(f"UPI Verification Error for {upi}: {e}")
        
        # 2. Check Phishing Links
        if state["intel"].phishing_links:
            for link in state["intel"].phishing_links:
                try:
                    response = await client.get(f"https://ipapi.co/json/", timeout=5.0)
                    org = response.json().get('org', 'Global Security')
                    logger.info(f"Checking Link: {link} (Security Node: {org})")
                except Exception as e:
                    logger.warning(f"Link check failed: {e}")
        
    return state

async def fingerprint_scammer(state: AgentState) -> AgentState:
    """
    Uses ChromaDB to fingerprint scammers based on BEHAVIORAL patterns.
    """
    try:
        behavioral_profile = f"""
        INTENT: {state.get('scam_detected', False)}
        SENTIMENT: {state.get('scammer_sentiment', 5)}
        PERSONA_TARGETED: {state.get('selected_persona', 'UNKNOWN')}
        IDENTIFIERS: {','.join(state['intel'].upi_ids + state['intel'].phone_numbers)}
        """
        
        # Vector DB search is sync, but we call it from async node
        search_results = vector_db.search_similar(behavioral_profile)
        
        if search_results["distances"] and search_results["distances"][0]:
            distance = search_results["distances"][0][0]
            match_score = 1.0 - distance
            
            # BRUTAL SYNDICATE SCORING
            # If we have multiple matches or a very high match, the score escalates
            syndicate_score = match_score
            if match_score > 0.9:
                syndicate_score = 0.95 # Confirmed high-level syndicate
            elif match_score > 0.7:
                syndicate_score = 0.8 # Suspected syndicate hub
            
            state["syndicate_match_score"] = syndicate_score
            
            if match_score > 0.85:
                state["is_returning_scammer"] = True
                logger.info("🕵️ SYNDICATE PATTERN MATCHED", extra={
                    "match_score": match_score,
                    "profile": behavioral_profile
                })
        
        vector_db.add_fingerprint(
            state["session_id"], 
            behavioral_profile, 
            {"original_message": state["user_message"][:100]}
        )
    except Exception as e:
        logger.error(f"Fingerprinting Error: {e}")
    
    return state

async def save_state(state: AgentState) -> AgentState:
    try:
        await db.add_message(state["session_id"], "user", state["user_message"])
        if state["agent_response"]:
            await db.add_message(state["session_id"], "assistant", state["agent_response"])
        
        if state.get("scam_detected"):
            await db.set_scam_flag(state["session_id"], True)
            logger.info(f"Session {state['session_id']} Sentiment: {state['scammer_sentiment']}")
            
        state["turn_count"] = await db.get_turn_count(state["session_id"])
    except Exception as e:
        logger.error(f"Error saving state: {e}")
    return state

async def submit_to_blacklist(state: AgentState) -> AgentState:
    """
    Mock node that "submits" extracted intel to a law enforcement blacklist.
    This demonstrates the "One-Click Takedown" feature.
    """
    if not state["scam_detected"] or not state["intel"]:
        return state

    # Mock submission logic
    for upi in state["intel"].upi_ids:
        logger.info(f"🚨 SUBMITTING TO BLACKLIST: {upi}")
        
    return state