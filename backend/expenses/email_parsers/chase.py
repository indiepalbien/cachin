import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any

from mailparser import parse_from_bytes


def _html_to_text(html: str) -> str:
    """Very light HTML to text: strip tags and collapse whitespace."""
    if not html:
        return ""
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Unescape basic entities
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_chase_alert(raw_eml: bytes) -> Dict[str, Any]:
    """Parse a Chase alert email and extract transaction data.

    Handles:
    - Direct deposits: "You have a direct deposit of $X"
    - Bill payments: "Your bill payment of $X to MERCHANT"

    Fields extracted:
    - description: "DIRECT DEPOSIT" or "BILL PAYMENT: MERCHANT"
    - source: "chase"
    - currency: "USD"
    - amount: Decimal (negative for deposits/income, positive for payments/expenses)
    - external_id: message-id header (fallback: generated from email data)
    """
    mp = parse_from_bytes(raw_eml)

    # Prefer plain text body; fallback to HTML converted text
    body_text = (mp.body or "").strip()
    if not body_text and mp.text_plain:
        body_text = "\n".join(mp.text_plain).strip()
    if not body_text and mp.text_html:
        body_text = _html_to_text("\n".join(mp.text_html))

    # Try to extract direct deposit
    deposit_match = re.search(
        r"You have a direct deposit of\s*(?:<[^>]*>)?\$?\s*([\d,\.]+)(?:<[^>]*>)?",
        body_text,
        re.IGNORECASE
    )

    # Try to extract bill payment
    payment_match = re.search(
        r'Your bill payment of \$([\d,]+(?:\.\d{2})?)\s+to\s+([^\n<]+)',
        body_text,
        re.IGNORECASE
    )

    amount: Optional[Decimal] = None
    description: str = ""

    if deposit_match:
        # Direct deposit (income) - negative amount
        try:
            amount_str = deposit_match.group(1).replace(',', '')
            amount = -Decimal(amount_str)
            description = "DIRECT DEPOSIT"
        except (InvalidOperation, ValueError):
            pass
    elif payment_match:
        # Bill payment (expense) - positive amount
        try:
            amount_str = payment_match.group(1).replace(',', '')
            amount = Decimal(amount_str)
            merchant = payment_match.group(2).strip()
            description = f"BILL PAYMENT: {merchant}"
        except (InvalidOperation, ValueError):
            pass

    # If no pattern matched, try generic amount extraction
    if amount is None:
        amount_match = re.search(r'\$?([\d,]+(?:\.\d{2})?)', body_text)
        if amount_match:
            try:
                amount_str = amount_match.group(1).replace(',', '')
                amount = Decimal(amount_str)
                description = mp.subject or "Chase transaction"
            except (InvalidOperation, ValueError):
                pass

    source = "chase"
    currency = "USD"

    message_id = (mp.message_id or "").strip()
    if not message_id:
        message_id = mp.headers.get("Message-Id") or mp.headers.get("Message-ID") or ""
    external_id = message_id or f"chase:{description}:{amount}"

    from_emails = [addr.lower() for _, addr in (mp.from_ or []) if addr]

    return {
        "description": description,
        "source": source,
        "currency": currency,
        "amount": amount,
        "external_id": external_id,
        "raw_body": body_text,
        "subject": mp.subject or "",
        "from_": mp.from_,
        "from_emails": from_emails,
        "to": mp.to,
        "message_id": message_id,
    }
