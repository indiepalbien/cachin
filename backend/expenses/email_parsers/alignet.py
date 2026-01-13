import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
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


def _clean_value(val: str) -> str:
    """Clean field value by removing HTML tags and entities."""
    if not val:
        return ""
    # Strip HTML tags and entities
    val = re.sub(r"<[^>]+>", " ", val)
    val = (
        val.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    val = re.sub(r"\s+", " ", val)
    return val.strip()


def _extract_field(text: str, label: str) -> Optional[str]:
    """Extract the value after `<label>:` in a case-insensitive manner."""
    pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.+)$", re.IGNORECASE)
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            return _clean_value(m.group(1))
    return None


def _detect_card_type(bin_digits: str) -> str:
    """
    Detect card type from BIN (Bank Identification Number) using first 4-6 digits.

    Args:
        bin_digits: First 4 digits of card number (e.g., "4111" for Visa test cards)

    Returns:
        Card type: "visa", "mastercard", "amex", "discover", or "unknown"
    """
    if not bin_digits or len(bin_digits) < 2:
        return "unknown"

    # Remove any non-digit characters
    digits = re.sub(r"\D", "", bin_digits)
    if not digits:
        return "unknown"

    # Get first digit and first 4 digits for checking
    first_digit = digits[0]
    first_two = digits[:2] if len(digits) >= 2 else digits
    first_four = digits[:4] if len(digits) >= 4 else digits

    # Visa: Starts with 4
    if first_digit == "4":
        return "visa"

    # Mastercard: 51-55 or 2221-2720
    if first_two in ["51", "52", "53", "54", "55"]:
        return "mastercard"
    if len(first_four) == 4:
        first_four_int = int(first_four)
        if 2221 <= first_four_int <= 2720:
            return "mastercard"

    # American Express: 34 or 37
    if first_two in ["34", "37"]:
        return "amex"

    # Discover: 6011, 622126-622925, 644-649, 65
    if first_four == "6011":
        return "discover"
    if first_two == "65":
        return "discover"
    if len(digits) >= 3:
        first_three = digits[:3]
        if first_three in ["644", "645", "646", "647", "648", "649"]:
            return "discover"
    if len(digits) >= 6:
        first_six = int(digits[:6])
        if 622126 <= first_six <= 622925:
            return "discover"

    return "unknown"


def _parse_alignet_date(date_str: str) -> Optional[date]:
    """
    Parse Alignet date format (DD/MM/YYYY).

    Args:
        date_str: Date string in DD/MM/YYYY format (e.g., "29/12/2025")

    Returns:
        date object or None if parsing fails
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def parse_alignet_alert(raw_eml: bytes) -> Dict[str, Any]:
    """Parse an Alignet security code email and extract transaction data.

    Handles Gmail-forwarded emails from payme@alignet.com.

    Fields extracted:
    - description: Comercio (merchant name)
    - source: "<cardtype>:<last4digits>" (e.g., "visa:1111", "mastercard:5678")
    - currency: Currency code (e.g., "UYU", "USD")
    - amount: Decimal amount
    - external_id: message-id header (fallback: generated hash)
    - date: Transaction date (from Fecha field, DD/MM/YYYY format)

    Security:
    - Does NOT extract or store the security code (Clave)
    - Only stores last 4 digits of card

    Args:
        raw_eml: Raw email bytes (RFC822 format)

    Returns:
        Dictionary with transaction fields matching standard parser format
    """
    mp = parse_from_bytes(raw_eml)

    # Prefer plain text body; fallback to HTML converted text
    body_text = (mp.body or "").strip()
    if not body_text and mp.text_plain:
        body_text = "\n".join(mp.text_plain).strip()
    if not body_text and mp.text_html:
        body_text = _html_to_text("\n".join(mp.text_html))

    # Extract merchant name
    # First try "Comercio:" label
    comercio = _extract_field(body_text, "Comercio")

    # If not found, look for merchant name (appears after card number line, before currency line)
    if not comercio:
        lines = body_text.splitlines()
        for i, line in enumerate(lines):
            # Look for card number pattern
            if re.search(r"\d{4}\*+\d{4}", line):
                # Merchant is likely on next non-empty line
                for j in range(i + 1, min(i + 5, len(lines))):
                    candidate = lines[j].strip()
                    # Skip empty lines and lines with known labels
                    if candidate and not any(label in candidate.upper() for label in ['CLAVE:', 'FECHA:', 'HORA:', 'UYU', 'USD', 'EUR', 'RECUERDE']):
                        comercio = candidate
                        break
                break

    description = comercio or (mp.subject or "Alignet Transaction")

    # Extract card number (format: 4111********1111 with masked middle digits)
    # Look for pattern: 4+ digits, asterisks, 4 digits
    card_pattern = r"(\d{4})\*+(\d{4})"
    card_match = re.search(card_pattern, body_text)

    source = None
    if card_match:
        first_four = card_match.group(1)
        last_four = card_match.group(2)
        card_type = _detect_card_type(first_four)
        source = f"{card_type}:{last_four}"
    else:
        # Fallback: try to extract just the last 4 digits
        source = "alignet"

    # Extract currency and amount
    # Format can be either:
    # 1. "UYU 4307.30" (currency and amount on same line)
    # 2. Separate "Moneda:" and "Monto:" labels
    currency = None
    amount = None

    # Try direct field extraction first (Moneda/Monto labels)
    moneda_line = _extract_field(body_text, "Moneda")
    monto_raw = _extract_field(body_text, "Monto")

    if moneda_line:
        # Extract currency code (first word, uppercase)
        currency = re.sub(r"<[^>]+>", "", moneda_line).split()[0].upper() if moneda_line else None

    if monto_raw:
        try:
            # Support both comma and period as decimal separator
            num = re.search(r"[-+]?\d+[\.,]?\d*", monto_raw)
            if num:
                amount_str = num.group(0).replace(',', '.')
                amount = Decimal(amount_str)
        except (InvalidOperation, AttributeError):
            amount = None

    # If not found via labels, look for "CURRENCY AMOUNT" pattern on same line
    if not currency or not amount:
        # Pattern: 3-letter currency code followed by amount
        # e.g., "UYU 4307.30" or "USD 123.45"
        currency_amount_pattern = r"^(USD|UYU|EUR|UYS|ARS|BRL|CLP|PEN)\s+(\d+(?:[.,]\d{2})?)\s*$"
        for line in body_text.splitlines():
            match = re.match(currency_amount_pattern, line.strip(), re.IGNORECASE)
            if match:
                currency = match.group(1).upper()
                try:
                    amount = Decimal(match.group(2).replace(',', '.'))
                except (InvalidOperation, AttributeError):
                    pass
                break

    # Extract date (Fecha: DD/MM/YYYY)
    fecha_raw = _extract_field(body_text, "Fecha")
    transaction_date = _parse_alignet_date(fecha_raw) if fecha_raw else None

    # Generate external_id (use message-id or create fallback)
    message_id = (mp.message_id or "").strip()
    if not message_id:
        message_id = mp.headers.get("Message-Id") or mp.headers.get("Message-ID") or ""

    # Fallback external_id (without sensitive data)
    if not message_id:
        external_id = f"alignet:{transaction_date}:{source}:{amount}:{currency}"
    else:
        external_id = message_id

    # Extract email metadata
    from_emails = [addr.lower() for _, addr in (mp.from_ or []) if addr]

    return {
        "description": description,
        "source": source,
        "currency": currency or "",
        "amount": amount,
        "external_id": external_id,
        "raw_body": body_text,
        "subject": mp.subject or "",
        "from_": mp.from_,
        "from_emails": from_emails,
        "to": mp.to,
        "message_id": message_id,
        "date": transaction_date,  # Include parsed date for potential use
    }
