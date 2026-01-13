"""
Parser for Gmail forwarding confirmation emails.

Detects and processes Gmail's automatic forwarding confirmation emails.
"""
import re
import logging
import quopri
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)


def _decode_header_value(header_value: str) -> str:
    """Decode an email header that may be encoded with =?charset?encoding?text?= format."""
    if not header_value:
        return ""
    
    try:
        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or 'utf-8', errors='ignore'))
            else:
                result.append(part)
        return ' '.join(result)
    except:
        return header_value


def is_gmail_forwarding_confirmation(from_address: str, subject: str) -> bool:
    """
    Check if this is a Gmail forwarding confirmation email.
    
    Args:
        from_address: The from email address
        subject: The email subject (may be encoded)
        
    Returns:
        True if this is a Gmail forwarding confirmation
    """
    from_lower = (from_address or "").lower()
    subject_decoded = _decode_header_value(subject).lower()
    
    return (
        "forwarding-noreply@google.com" in from_lower
        and ("confirmación" in subject_decoded or "confirmation" in subject_decoded)
        and ("reenvío" in subject_decoded or "forwarding" in subject_decoded)
    )


def extract_confirmation_link(raw_body: bytes) -> Optional[str]:
    """
    Extract the confirmation link from Gmail forwarding email body.
    
    Args:
        raw_body: The raw email body bytes (may be quoted-printable)
        
    Returns:
        The confirmation URL or None if not found
    """
    # Decode quoted-printable if needed
    try:
        decoded = quopri.decodestring(raw_body).decode('utf-8', errors='ignore')
    except:
        decoded = raw_body.decode('utf-8', errors='ignore') if isinstance(raw_body, bytes) else str(raw_body)
    
    # Remove any soft line breaks (= at end of line in quoted-printable)
    decoded = decoded.replace('=\n', '').replace('=\r\n', '')
    
    # Pattern to match Gmail verification links
    # They start with https://mail-settings.google.com/mail/vf-
    pattern = r'https://mail-settings\.google\.com/mail/vf-[^\s<>]+'
    
    matches = re.findall(pattern, decoded)
    if matches:
        # Get the first match and clean up
        link = matches[0]
        # Remove any trailing punctuation
        link = link.rstrip('.,;)')
        logger.info(f"Found Gmail confirmation link: {link[:100]}...")
        return link
    
    logger.warning("Could not extract confirmation link from Gmail forwarding email")
    return None


def parse_gmail_forwarding_email(raw_body: bytes) -> dict:
    """
    Parse a Gmail forwarding confirmation email.
    
    Args:
        raw_body: The raw email body bytes
        
    Returns:
        Dict with:
            - confirmation_link: The verification URL
            - forwarding_email: The email requesting to forward (if found)
    """
    result = {
        "confirmation_link": None,
        "forwarding_email": None,
    }
    
    # Extract confirmation link
    result["confirmation_link"] = extract_confirmation_link(raw_body)
    
    # Decode for text parsing
    try:
        decoded = quopri.decodestring(raw_body).decode('utf-8', errors='ignore')
    except:
        decoded = raw_body.decode('utf-8', errors='ignore') if isinstance(raw_body, bytes) else str(raw_body)
    
    # Try to extract the forwarding email (quien solicita el reenvío)
    # Pattern: email@example.com ha solicitado reenviar
    email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s+ha\s+solicitado\s+reenviar'
    email_matches = re.findall(email_pattern, decoded)
    if email_matches:
        result["forwarding_email"] = email_matches[0]
        logger.info(f"Found forwarding email: {result['forwarding_email']}")
    
    return result

