import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any

from mailparser import parse_from_bytes


def parse_ibkr_trade(raw_eml: bytes) -> Dict[str, Any]:
    """Parse an Interactive Brokers trade confirmation email and extract stock data.

    Subject line format: "BOUGHT 10 AAPL @ 150.50" or "SOLD 5.5 MSFT @ 300.25"

    Fields extracted:
    - symbol: Stock ticker (e.g., "AAPL", "MSFT")
    - bought: True for BUY, False for SELL
    - amount: Number of shares (Decimal)
    - unitprice: Price per share in USD (Decimal)
    - external_id: message-id header (fallback: generated from trade data)

    Returns None if the email doesn't match the expected format.
    """
    mp = parse_from_bytes(raw_eml)

    subject = mp.subject or ""

    # Pattern to match: BOUGHT/SOLD quantity symbol @ price
    # Supports decimals in quantity and price
    pattern = r'(BOUGHT|SOLD)\s+(\d+\.?\d*|\.\d+)\s+([A-Z0-9]+(?:\s+[A-Z]+)*)\s+@\s+(\d+\.?\d*|\.\d+)'

    match = re.search(pattern, subject, re.IGNORECASE)

    if not match:
        return None

    action = match.group(1).upper()
    bought = (action == 'BOUGHT')

    try:
        amount = Decimal(match.group(2))
        symbol = match.group(3).strip().upper()
        unitprice = Decimal(match.group(4))
    except (InvalidOperation, ValueError):
        return None

    message_id = (mp.message_id or "").strip()
    if not message_id:
        message_id = mp.headers.get("Message-Id") or mp.headers.get("Message-ID") or ""
    external_id = message_id or f"ibkr:{action}:{symbol}:{amount}:{unitprice}"

    from_emails = [addr.lower() for _, addr in (mp.from_ or []) if addr]

    # Calculate total value for the transaction
    total_value = amount * unitprice

    return {
        "symbol": symbol,
        "bought": bought,
        "amount": amount,
        "unitprice": unitprice,
        "total_value": total_value,
        "external_id": external_id,
        "subject": subject,
        "from_": mp.from_,
        "from_emails": from_emails,
        "to": mp.to,
        "message_id": message_id,
    }
