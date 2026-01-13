# Midinero Email Formats Proposal

## Overview

Parser formats for three types of Midinero transaction alerts from `noreply@midinero.com.uy`.

**IMPORTANT**: All data has been anonymized/mocked for security.

---

## Transaction Fields

- **description**: Transaction description
- **date**: Transaction date
- **currency**: 3-letter code (UYU, USD, etc.)
- **amount**: Decimal (positive for expenses, negative for income)
- **external_id**: Unique identifier
- **source**: Optional account reference

---

## Email Formats

### 1. Consumption Alert
**Subject**: `Aviso consumo por $XXX.XX`

Fields:
- Fecha y hora → date
- Comercio → description
- Nº cuenta → source
- Moneda → currency
- Total Pesos → amount (positive)

### 2. Reload Alert
**Subject**: `Aviso recarga por $X,XXX.XX`

Fields:
- Fecha y hora → date
- Cuenta → source
- Moneda → currency
- Total Pesos → amount (NEGATIVE for income)

### 3. Transfer Alert
**Subject**: `Tu transferencia ha sido acreditada (referencia: XXXXXXXXX).`

Fields:
- Enviada → date
- Cuenta origen → source
- Institución destino → description
- Moneda → currency
- Total Pesos → amount (positive)

---

## Amount Signs

| Type | Sign | Why |
|------|------|-----|
| Consumption | + | Expense |
| Reload | **-** | Income |
| Transfer | + | Expense |

---

## Currency Handling

### Currency Mapping

The "Moneda" field might contain text like:
- "Uruguayan Pesos" → UYU
- "Pesos" → UYU
- "USD" → USD
- "US Dollars" → USD
- "Dólares" → USD

```python
def _normalize_currency(currency_text: str) -> str:
    """Convert currency text to 3-letter code."""
    if not currency_text:
        return "UYU"  # Fallback default

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

    # Fallback
    return "UYU"
```

### Amount Parsing

Format: `1.234,56` → `1234.56`

```python
def _parse_amount(amount_str: str) -> Optional[Decimal]:
    """Parse: 1.234,56 -> 1234.56"""
    amount_str = re.sub(r'[$\s]', '', amount_str)
    amount_str = amount_str.replace('.', '')   # Remove thousands
    amount_str = amount_str.replace(',', '.')  # Fix decimal
    try:
        return Decimal(amount_str)
    except InvalidOperation:
        return None
```

---

## Date Parsing

Format: `DD/MM/YYYY HH:MM` → `YYYY-MM-DD`

```python
def _parse_date(date_str: str) -> str:
    """Parse DD/MM/YYYY HH:MM -> YYYY-MM-DD"""
    dt = datetime.strptime(date_str[:16], "%d/%m/%Y %H:%M")
    return dt.date().isoformat()
```

---

## Sender Detection

**For forwarded emails**, check body for `noreply@midinero.com.uy`:

```python
def _is_midinero_email(raw_eml: bytes) -> bool:
    """Check if from Midinero (including forwarded)."""
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
```

---

## Full Implementation

File: `backend/expenses/email_parsers/midinero.py`

```python
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Optional, Dict, Any
from mailparser import parse_from_bytes


def _html_to_text(html: str) -> str:
    """Strip HTML tags."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_field(text: str, label: str) -> Optional[str]:
    """Extract value after 'Label:' pattern."""
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)
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
    """Parse: 1.234,56 -> 1234.56"""
    amount_str = re.sub(r'[$\s]', '', amount_str)
    amount_str = amount_str.replace('.', '')
    amount_str = amount_str.replace(',', '.')
    try:
        return Decimal(amount_str)
    except InvalidOperation:
        return None


def _parse_date(date_str: str) -> str:
    """Parse DD/MM/YYYY HH:MM -> YYYY-MM-DD"""
    dt = datetime.strptime(date_str[:16], "%d/%m/%Y %H:%M")
    return dt.date().isoformat()


def _is_midinero_email(raw_eml: bytes) -> bool:
    """Check if from Midinero (including forwarded)."""
    mp = parse_from_bytes(raw_eml)

    # Check From
    from_emails = [addr.lower() for _, addr in (mp.from_ or [])]
    if 'noreply@midinero.com.uy' in from_emails:
        return True

    # Check body for forwarded
    body = mp.body or ""
    if not body and mp.text_html:
        body = _html_to_text("\n".join(mp.text_html))

    return 'noreply@midinero.com.uy' in body.lower()


def parse_midinero_consumption(raw_eml: bytes) -> Dict[str, Any]:
    """Parse consumption alert."""
    mp = parse_from_bytes(raw_eml)

    body = mp.body or ""
    if not body and mp.text_html:
        body = _html_to_text("\n".join(mp.text_html))

    # Extract
    fecha_hora = _extract_field(body, "Fecha y hora")
    comercio = _extract_field(body, "Comercio")
    cuenta = _extract_field(body, "N.? cuenta")
    moneda = _extract_field(body, "Moneda")
    total = _extract_field(body, "Total Pesos")

    # Parse
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
    """Parse reload alert."""
    mp = parse_from_bytes(raw_eml)

    body = mp.body or ""
    if not body and mp.text_html:
        body = _html_to_text("\n".join(mp.text_html))

    fecha_hora = _extract_field(body, "Fecha y hora")
    cuenta = _extract_field(body, "Cuenta")
    moneda = _extract_field(body, "Moneda")
    total = _extract_field(body, "Total Pesos")

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
        "amount": amount,
        "external_id": message_id,
        "source": f"midinero:{cuenta}" if cuenta else None,
    }


def parse_midinero_transfer(raw_eml: bytes) -> Dict[str, Any]:
    """Parse transfer alert."""
    mp = parse_from_bytes(raw_eml)

    body = mp.body or ""
    if not body and mp.text_html:
        body = _html_to_text("\n".join(mp.text_html))

    enviada = _extract_field(body, "Enviada")
    cuenta_origen = _extract_field(body, "Cuenta origen")
    institucion = _extract_field(body, "Instituci.n destino")
    moneda = _extract_field(body, "Moneda")
    total = _extract_field(body, "Total Pesos")

    date = _parse_date(enviada) if enviada else None
    amount = _parse_amount(total) if total else None
    currency = _normalize_currency(moneda) if moneda else "UYU"
    message_id = mp.message_id or f"midinero:transfer:{date}:{amount}"

    description = f"Transferencia a {institucion}" if institucion else "Transferencia"

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
    Returns None if not Midinero.
    """
    if not _is_midinero_email(raw_eml):
        return None

    mp = parse_from_bytes(raw_eml)
    subject = (mp.subject or "").strip()

    # Detect type
    if re.search(r"Aviso consumo por", subject):
        return parse_midinero_consumption(raw_eml)
    elif re.search(r"Aviso recarga por", subject):
        return parse_midinero_reload(raw_eml)
    elif re.search(r"Tu transferencia ha sido acreditada", subject):
        return parse_midinero_transfer(raw_eml)

    return None
```

---

## Summary

1. **Currency mapping**: "Uruguayan Pesos" → UYU, "Dólares" → USD, etc.
2. **Check body for sender**: For forwarded emails
3. **Amount signs**: Consumption/Transfer = +, Reload = -
4. **Parse format**: 1.234,56 → 1234.56

---

**Version**: 4.0 (Final with currency mapping)
**Date**: 2026-01-07
**Status**: Ready for Implementation
