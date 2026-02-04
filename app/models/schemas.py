from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class ScammerInput(BaseModel):
    session_id: str
    message: str
    generate_report: bool = False
    metadata: Optional[Dict] = {}

class ExtractedIntel(BaseModel):
    upi_ids: List[str] = []
    bank_details: List[str] = []
    phishing_links: List[str] = []

class AgentResponse(BaseModel):
    session_id: str
    scam_detected: bool
    response: str
    extracted_intelligence: ExtractedIntel
    report_url: Optional[str] = None
    metrics: Dict[str, int]