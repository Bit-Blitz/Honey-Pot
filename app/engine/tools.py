import re
from app.models.schemas import ExtractedIntel

def extract_intelligence(text: str) -> ExtractedIntel:
    intel = ExtractedIntel()
    
    # Regex for UPI IDs
    upi_pattern = r'[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}'
    intel.upi_ids = list(set(re.findall(upi_pattern, text)))

    # Regex for URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
    intel.phishing_links = list(set(re.findall(url_pattern, text)))

    # Heuristic for Bank Accounts (9-18 digits)
    digit_pattern = r'\b\d{9,18}\b'
    intel.bank_details = list(set(re.findall(digit_pattern, text)))

    return intel