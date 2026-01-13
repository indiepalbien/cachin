import re
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Optional, Dict, Any
from mailparser import parse_from_bytes


def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_field(text: str, label: str) -> Optional[str]:
    """Extract value after 'Label:' pattern."""
    # Try with exact match first
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)
    m = pattern.search(text)
    if m:
        return m.group(1).strip()

    # Try with regex for special characters (like º in "Nº")
    pattern = re.compile(rf"{re.escape(label).replace('o', '[oóº]')}\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _normalize_currency(currency_text: str) -> str:
    """Convert currency text to 3-letter code."""
    if not currency_text:
        return "UYU"

    text = currency_text.upper().strip()

    # Direct matches
    if text in ["UYU", "USD", "EUR", "BRL"]:
        return text

    # Text mappings
    mappings = {
        "URUGUAYAN PESOS": "UYU",
        "PESOS URUGUAYOS": "UYU",
        "PESOS": "UYU",
        "US DOLLARS": "USD",
        "DOLARES": "USD",
        "DÓLARES": "USD",
        "DOLLARS": "USD",
        "EUROS": "EUR",
        "REALES": "BRL",
    }

    for key, code in mappings.items():
        if key in text:
            return code

    return "UYU"


def _parse_amount(amount_str: str) -> Optional[Decimal]:
    """Parse Uruguayan format: 1.234,56 -> 1234.56"""
    if not amount_str:
        return None
    amount_str = re.sub(r'[$\s]', '', amount_str)
    amount_str = amount_str.replace('.', '')   # Remove thousands separator
    amount_str = amount_str.replace(',', '.')  # Fix decimal separator
    try:
        return Decimal(amount_str)
    except InvalidOperation:
        return None


def _parse_date(date_str: str) -> Optional[str]:
    """Parse DD/MM/YYYY HH:MM -> YYYY-MM-DD"""
    if not date_str:
        return None
    try:
        # Extract just the date and time parts
        parts = date_str.strip().split()
        if len(parts) >= 2:
            date_part = parts[0]
            time_part = parts[1]
            dt = datetime.strptime(f"{date_part} {time_part}", "%d/%m/%Y %H:%M")
            return dt.date().isoformat()
    except (ValueError, IndexError):
        pass
    return None


def _is_midinero_email(raw_eml: bytes) -> bool:
    """Check if email is from Midinero (including forwarded)."""
    mp = parse_from_bytes(raw_eml)

    # Check From header
    from_emails = [addr.lower() for _, addr in (mp.from_ or [])]
    if 'noreply@midinero.com.uy' in from_emails:
        return True

    # Check body for forwarded emails
    body = mp.body or ""
    if not body and mp.text_html:
        body = _html_to_text("\n".join(mp.text_html))

    return 'noreply@midinero.com.uy' in body.lower()


def parse_midinero_consumption(raw_eml: bytes) -> Dict[str, Any]:
    """Parse Midinero consumption alert."""
    mp = parse_from_bytes(raw_eml)

    # Extract from HTML directly (table structure)
    html = "\n".join(mp.text_html) if mp.text_html else ""

    # Extract fields using regex on HTML
    fecha_hora_match = re.search(r'Fecha y hora.*?<b>([^<]+)</b>', html, re.DOTALL)
    comercio_match = re.search(r'Comercio.*?<b>([^<]+)</b>', html, re.DOTALL)
    cuenta_match = re.search(r'N[^<]*cuenta.*?<b>([^<]+)</b>', html, re.DOTALL)
    moneda_match = re.search(r'Moneda.*?<b>([^<]+)</b>', html, re.DOTALL)
    total_match = re.search(r'Total Pesos.*?\$\s*([\d.,]+)', html, re.DOTALL)

    fecha_hora = fecha_hora_match.group(1).strip() if fecha_hora_match else None
    comercio = comercio_match.group(1).strip() if comercio_match else None
    cuenta = cuenta_match.group(1).strip() if cuenta_match else None
    moneda = moneda_match.group(1).strip() if moneda_match else None
    total = total_match.group(1).strip() if total_match else None

    # Parse values
    date = _parse_date(fecha_hora) if fecha_hora else None
    amount = _parse_amount(total) if total else None
    currency = _normalize_currency(moneda) if moneda else "UYU"
    message_id = mp.message_id or f"midinero:consumption:{date}:{amount}"

    return {
        "description": comercio or mp.subject or "Consumo Midinero",
        "date": date,
        "currency": currency,
        "amount": amount,
        "external_id": message_id,
        "source": f"midinero:{cuenta}" if cuenta else None,
    }


def parse_midinero_reload(raw_eml: bytes) -> Dict[str, Any]:
    """Parse Midinero reload alert."""
    mp = parse_from_bytes(raw_eml)

    # Extract from HTML directly (table structure)
    html = "\n".join(mp.text_html) if mp.text_html else ""

    # Extract fields using regex on HTML
    fecha_hora_match = re.search(r'Fecha y hora.*?<b>([^<]+)</b>', html, re.DOTALL)
    cuenta_match = re.search(r'Cuenta</div>.*?<b>([0-9]{6,})</b>', html, re.DOTALL)
    moneda_match = re.search(r'Moneda.*?<b>([^<]+)</b>', html, re.DOTALL)
    total_match = re.search(r'Total Pesos.*?\$\s*([\d.,]+)', html, re.DOTALL)

    fecha_hora = fecha_hora_match.group(1).strip() if fecha_hora_match else None
    cuenta = cuenta_match.group(1).strip() if cuenta_match else None
    moneda = moneda_match.group(1).strip() if moneda_match else None
    total = total_match.group(1).strip() if total_match else None

    date = _parse_date(fecha_hora) if fecha_hora else None
    amount = _parse_amount(total) if total else None
    currency = _normalize_currency(moneda) if moneda else "UYU"

    # Make NEGATIVE for income
    if amount is not None:
        amount = -amount

    message_id = mp.message_id or f"midinero:reload:{date}:{amount}"

    return {
        "description": "Recarga Midinero",
        "date": date,
        "currency": currency,
        "amount": amount,  # NEGATIVE
        "external_id": message_id,
        "source": f"midinero:{cuenta}" if cuenta else None,
    }


def parse_midinero_transfer(raw_eml: bytes) -> Dict[str, Any]:
    """Parse Midinero transfer alert."""
    mp = parse_from_bytes(raw_eml)

    # Extract from HTML directly (table structure)
    html = "\n".join(mp.text_html) if mp.text_html else ""

    # Extract fields using regex on HTML
    enviada_match = re.search(r'Enviada.*?<b>([^<]+)</b>', html, re.DOTALL)
    cuenta_origen_match = re.search(r'Cuenta origen.*?([0-9]{6,})', html, re.DOTALL)
    institucion_match = re.search(r'Instituci(?:&oacute;|ó)n destino.*?<b>([^<]+)</b>', html, re.DOTALL)
    cuenta_destino_match = re.search(r'Cuenta destino.*?<b>([0-9]+)</b>', html, re.DOTALL)
    nombre_destino_match = re.search(r'Nombre destino.*?<b>([^<]+)</b>', html, re.DOTALL)
    moneda_match = re.search(r'Moneda.*?<b>([^<]+)</b>', html, re.DOTALL)
    total_match = re.search(r'Total Pesos.*?\$\s*([\d.,]+)', html, re.DOTALL)

    enviada = enviada_match.group(1).strip() if enviada_match else None
    cuenta_origen = cuenta_origen_match.group(1).strip() if cuenta_origen_match else None
    institucion = institucion_match.group(1).strip() if institucion_match else None
    cuenta_destino = cuenta_destino_match.group(1).strip() if cuenta_destino_match else None
    nombre_destino = nombre_destino_match.group(1).strip() if nombre_destino_match else None
    moneda = moneda_match.group(1).strip() if moneda_match else None
    total = total_match.group(1).strip() if total_match else None

    date = _parse_date(enviada) if enviada else None
    amount = _parse_amount(total) if total else None
    currency = _normalize_currency(moneda) if moneda else "UYU"
    message_id = mp.message_id or f"midinero:transfer:{date}:{amount}"

    # Build description: "Transferencia a NOMBRE (Institucion, cuenta)"
    if nombre_destino and institucion and cuenta_destino:
        description = f"Transferencia a {nombre_destino} ({institucion}, {cuenta_destino})"
    elif nombre_destino:
        description = f"Transferencia a {nombre_destino}"
    elif institucion:
        description = f"Transferencia a {institucion}"
    else:
        description = "Transferencia Midinero"

    return {
        "description": description,
        "date": date,
        "currency": currency,
        "amount": amount,
        "external_id": message_id,
        "source": f"midinero:{cuenta_origen}" if cuenta_origen else None,
    }


def parse_midinero_alert(raw_eml: bytes) -> Optional[Dict[str, Any]]:
    """
    Detect and parse Midinero email.
    Returns None if not a Midinero email.
    """
    if not _is_midinero_email(raw_eml):
        return None

    mp = parse_from_bytes(raw_eml)
    subject = (mp.subject or "").strip()

    # Detect type by subject
    if re.search(r"Aviso consumo por", subject, re.IGNORECASE):
        return parse_midinero_consumption(raw_eml)
    elif re.search(r"Aviso recarga por", subject, re.IGNORECASE):
        return parse_midinero_reload(raw_eml)
    elif re.search(r"Tu transferencia ha sido acreditada", subject, re.IGNORECASE):
        return parse_midinero_transfer(raw_eml)

    return None
