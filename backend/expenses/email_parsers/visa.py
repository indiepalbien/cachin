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


def _clean_value(val: str) -> str:
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


def parse_visa_alert(raw_eml: bytes) -> Dict[str, Any]:
    """Parse a Visa alert email and extract transaction data.

    Fields extracted:
    - description: Comercio
    - source: Tarjeta, prefixed with "visa:" (e.g., visa:1234)
    - currency: Moneda (e.g., USD)
    - amount: Monto (Decimal)
    - comments: Original amount and currency when approximated (e.g., "Original: 4.99 EUR")
    - external_id: message-id header (fallback: subject hash)

    When the transaction is in a currency other than USD or UYU and includes an
    approximated USD value (e.g., "4.99 (aproximadamente 6.05 USD)"), the parser
    will use the approximated USD value as the amount and store the original value
    in comments.

    We ignore Autorización/Referencia for now, but we can extend.
    """
    mp = parse_from_bytes(raw_eml)

    # Prefer plain text body; fallback to HTML converted text
    body_text = (mp.body or "").strip()
    if not body_text and mp.text_plain:
        body_text = "\n".join(mp.text_plain).strip()
    if not body_text and mp.text_html:
        body_text = _html_to_text("\n".join(mp.text_html))

    comercio = _extract_field(body_text, "Comercio")
    tarjeta = _extract_field(body_text, "Tarjeta")
    moneda = _extract_field(body_text, "Moneda")
    monto_raw = _extract_field(body_text, "Monto")

    description = comercio or (mp.subject or "")
    source = f"visa:{tarjeta}" if tarjeta else None
    currency = (moneda or "").split()[0].replace('<br>', '').upper()

    amount: Optional[Decimal] = None
    original_amount_comment: Optional[str] = None

    if monto_raw:
        # Check for approximated USD value: "4.99 (aproximadamente 6.05 USD)"
        approx_match = re.search(
            r"([-+]?\d+[.,]?\d*)\s*\(aproximadamente\s+([-+]?\d+[.,]?\d*)\s+USD\)",
            monto_raw,
            re.IGNORECASE
        )

        if approx_match and currency not in ['USD', 'UYU']:
            # Use approximated USD value as the main amount
            try:
                original_amount = Decimal(approx_match.group(1).replace(',', '.'))
                amount = Decimal(approx_match.group(2).replace(',', '.'))
                # Store original amount and currency in comment
                original_amount_comment = f"Original: {original_amount} {currency}"
                # Change currency to USD since we're using the approximated value
                currency = 'USD'
            except (InvalidOperation, AttributeError):
                # Fallback to regular parsing if conversion fails
                amount = None

        # Fallback to regular amount extraction if no approximation found
        if amount is None:
            try:
                num = re.search(r"[-+]?\d+[\.,]?\d*", monto_raw)
                if num:
                    amount = Decimal(num.group(0).replace(',', '.'))
            except (InvalidOperation, AttributeError):
                amount = None

    message_id = (mp.message_id or "").strip()
    if not message_id:
        message_id = mp.headers.get("Message-Id") or mp.headers.get("Message-ID") or ""
    external_id = message_id or f"visa:{description}:{source}:{amount}:{currency}"

    from_emails = [addr.lower() for _, addr in (mp.from_ or []) if addr]

    return {
        "description": description,
        "source": source,
        "currency": currency,
        "amount": amount,
        "comments": original_amount_comment or "",
        "external_id": external_id,
        "raw_body": body_text,
        "subject": mp.subject or "",
        "from_": mp.from_,
        "from_emails": from_emails,
        "to": mp.to,
        "message_id": message_id,
    }
