import re
from app.models.schemas import ExtractedIntel

def extract_intelligence(text: str) -> ExtractedIntel:
    intel = ExtractedIntel()
    
    # Normalize text for better extraction (handle some obfuscation)
    # 1. Remove common separators between digits in what looks like a bank account
    normalized_text = text.lower()
    
    # Regex for UPI IDs
    upi_pattern = r'[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}'
    intel.upi_ids = list(set(re.findall(upi_pattern, text)))

    # Regex for URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
    intel.phishing_links = list(set(re.findall(url_pattern, text)))

    # Heuristic for Bank Accounts (9-18 digits)
    # Try finding digits even with spaces or dashes between them
    digit_sequences = re.findall(r'(?:\d[\s-]*){9,18}\d', text)
    cleaned_digits = [re.sub(r'[\s-]', '', d) for d in digit_sequences]
    intel.bank_details = list(set(cleaned_digits))

    return intel