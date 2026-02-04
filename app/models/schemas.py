from pydantic import BaseModel, Field, AliasChoices
from typing import List, Dict, Optional

class Message(BaseModel):
    sender: str
    text: str
    timestamp: Optional[int] = None

class Metadata(BaseModel):
    channel: Optional[str] = "SMS"
    language: Optional[str] = "English"
    locale: Optional[str] = "IN"

class ScammerInput(BaseModel):
    api_key: Optional[str] = Field(None, alias="apiKey") # Support both api_key and apiKey
    session_id: str = Field(..., validation_alias=AliasChoices("sessionId", "session_id"))
    message: Message
    conversation_history: List[Message] = Field(default=[], validation_alias=AliasChoices("conversationHistory", "conversation_history"))
    metadata: Optional[Metadata] = Field(default_factory=Metadata)
    
    # Internal flags (not from hackathon schema but kept for system logic)
    generate_report: bool = False
    human_intervention: bool = False 

class ExtractedIntel(BaseModel):
    upi_ids: List[str] = []
    bank_details: List[str] = []
    phishing_links: List[str] = []
    phone_numbers: List[str] = []
    suspicious_keywords: List[str] = [] # Added for callback
    agent_notes: Optional[str] = None # Added for callback

class AgentResponse(BaseModel):
    status: str = "success"
    reply: str
    metadata: Optional[Dict] = None # Added for syndicate scoring/extra info

class CallbackPayload(BaseModel):
    sessionId: str
    scamDetected: bool
    totalMessagesExchanged: int
    extractedIntelligence: Dict[str, List[str]]
    agentNotes: str