import logging
import re as _re
from datetime import date, datetime as datetime_class
from email.utils import parseaddr
from typing import Optional

from django.db import transaction, IntegrityError
from django.utils import timezone

from expenses.email_parsers.visa import parse_visa_alert
from expenses.email_parsers.chase import parse_chase_alert
from expenses.email_parsers.ibkr import parse_ibkr_trade
from expenses.email_parsers.alignet import parse_alignet_alert
from expenses.email_parsers.midinero import parse_midinero_alert
from expenses.email_parsers.gmail_forwarding import (
    is_gmail_forwarding_confirmation,
    parse_gmail_forwarding_email,
)
from expenses.models import (
    Category,
    Exchange,
    IBKRSymbolCurrency,
    PendingTransaction,
    Source,
    Stock,
    Transaction as Tx,
    UserEmailMessage,
    UserEmailConfig,
)


logger = logging.getLogger(__name__)

_FOREX_PATTERN = _re.compile(r'^[A-Z]{3}\.[A-Z]{3}$')
_IBKR_DEPOSIT_MARKER = "interactive brokers"


def _is_forex(symbol: str) -> bool:
    """Return True if symbol is a currency pair like EUR.USD."""
    return bool(_FOREX_PATTERN.match(symbol))


def _symbol_key(symbol: str) -> str:
    """Extract the primary ticker for use as a sub-source key.

    'SUSW LSEETF' -> 'SUSW'
    'AAPL'        -> 'AAPL'
    """
    return symbol.split()[0]


def _convert_usd_to_currency(amount_usd, target_currency: str, trade_date, user):
    """Convert a USD amount to target_currency using Exchange rates.

    Looks up the most recent exchange rate on or before trade_date.
    Returns a Decimal or None if no rate is found.
    """
    from decimal import Decimal

    if target_currency.upper() == "USD":
        return Decimal(str(amount_usd))

    # Direct: USD -> target
    direct = (
        Exchange.objects.filter(
            user=user,
            source_currency__iexact="USD",
            target_currency__iexact=target_currency,
            date__lte=trade_date,
        )
        .order_by("-date")
        .first()
    )
    if direct:
        try:
            return (Decimal(str(amount_usd)) * direct.rate).quantize(Decimal("0.01"))
        except Exception:
            pass

    # Inverse: target -> USD, then divide
    inverse = (
        Exchange.objects.filter(
            user=user,
            source_currency__iexact=target_currency,
            target_currency__iexact="USD",
            date__lte=trade_date,
        )
        .order_by("-date")
        .first()
    )
    if inverse and inverse.rate:
        try:
            return (Decimal(str(amount_usd)) / inverse.rate).quantize(Decimal("0.01"))
        except Exception:
            pass

    return None


def _get_investments_category(user):
    """Get or create the 'investments' category for IBKR transactions."""
    cat, _ = Category.objects.get_or_create(
        user=user, name="investments",
        defaults={"counts_to_total": False},
    )
    return cat


def _get_or_create_source(user, source_name: str) -> Optional[Source]:
    if not source_name:
        return None
    obj, _ = Source.objects.get_or_create(user=user, name=source_name)
    return obj


def process_new_messages() -> int:
    """Process unprocessed UserEmailMessage entries and create transactions or pending duplicates.

    Returns the count of processed messages.
    """
    qs = UserEmailMessage.objects.filter(processed_at__isnull=True)
    count = 0
    for msg in qs.iterator():
        try:
            logger.info("📧 Processing email msg_id=%s subject='%s' user=%s",
                       msg.message_id, msg.subject, msg.user_id)

            envelope_from = parseaddr(msg.from_address or "")[1].lower()
            subject = (msg.subject or "").lower()

            # Check if this is a Gmail forwarding confirmation email
            if is_gmail_forwarding_confirmation(envelope_from, msg.subject or ""):
                count += _process_gmail_confirmation(msg)
                continue

            # Detect email type and route to appropriate handler
            if envelope_from == "no.reply.alerts@chase.com" and ("direct deposit" in subject or "bill payment" in subject):
                count += _process_chase_alert(msg)
            elif envelope_from == "tradingassistant@interactivebrokers.com":
                count += _process_ibkr_trade(msg)
            elif "donotreplyalertadecomprasvisa@visa.com" in envelope_from or "visa" in subject:
                count += _process_visa_alert(msg)
            elif "alignet" in subject or "código de seguridad" in subject:
                count += _process_alignet_alert(msg)
            elif envelope_from == "noreply@midinero.com.uy" or "midinero" in envelope_from or "midinero.com.uy" in (msg.raw_eml or b"").decode("utf-8", errors="ignore").lower():
                count += _process_midinero_alert(msg)
            else:
                logger.warning("⚠️  SKIPPED msg_id=%s reason=unrecognized_sender envelope_from=%s",
                              msg.message_id, envelope_from)
                msg.processing_error = f"Unrecognized sender: {envelope_from}"
                msg.processed_at = timezone.now()
                msg.save(update_fields=["processing_error", "processed_at"])

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {str(exc)}"
            logger.error(
                "❌ FAILED processing msg_id=%s subject='%s' user=%s\n   Error: %s",
                msg.message_id,
                msg.subject,
                msg.user_id,
                error_msg,
                exc_info=True
            )
            msg.processing_error = error_msg[:500]
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
    return count


def _process_gmail_confirmation(msg: UserEmailMessage) -> int:
    """Process Gmail forwarding confirmation emails."""
    logger.info("🔑 Gmail forwarding confirmation detected msg_id=%s", msg.message_id)
    try:
        parsed_gmail = parse_gmail_forwarding_email(bytes(msg.raw_eml))
        confirmation_link = parsed_gmail.get("confirmation_link")

        update_fields = ["processed_at"]
        if confirmation_link:
            logger.info("🔗 Storing forwarding confirmation link: %s", confirmation_link[:80])
            msg.gmail_confirmation_link = confirmation_link
            update_fields.append("gmail_confirmation_link")
            logger.info("✅ Gmail forwarding link stored for user=%s", msg.user_id)
        else:
            logger.warning("⚠️  No confirmation link found in Gmail forwarding email")

        msg.processed_at = timezone.now()
        msg.save(update_fields=update_fields)
        return 1

    except Exception as e:
        logger.error("❌ Failed to process Gmail forwarding confirmation: %s", str(e), exc_info=True)
        msg.processing_error = f"Gmail forwarding error: {str(e)}"[:500]
        msg.processed_at = timezone.now()
        msg.save(update_fields=["processing_error", "processed_at"])
        return 1


def _process_visa_alert(msg: UserEmailMessage) -> int:
    """Process VISA transaction alert emails."""
    parsed = None
    try:
        parsed = parse_visa_alert(bytes(msg.raw_eml))
        logger.info("✓ Parsed VISA email msg_id=%s amount=%s currency=%s description='%s'",
                   msg.message_id, parsed.get("amount"), parsed.get("currency"),
                   parsed.get("description", "")[:50])

        # Gate by sender
        envelope_from = parseaddr(msg.from_address or "")[1].lower()
        parsed_froms = parsed.get("from_emails") or []
        body = (parsed.get("raw_body") or "").lower()
        allowed_sender = "donotreplyalertadecomprasvisa@visa.com"

        if not (envelope_from == allowed_sender or allowed_sender in parsed_froms or allowed_sender in body):
            logger.warning("⚠️  SKIPPED msg_id=%s reason=sender_mismatch", msg.message_id)
            msg.processing_error = "skipped_non_visa_sender"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        if not parsed.get("amount") or not parsed.get("currency"):
            logger.warning("⚠️  SKIPPED msg_id=%s reason=missing_amount_currency", msg.message_id)
            msg.processing_error = "Missing amount or currency"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        return _create_transaction(msg, parsed)

    except IntegrityError as exc:
        return _handle_duplicate(msg, parsed, exc)


def _process_chase_alert(msg: UserEmailMessage) -> int:
    """Process Chase transaction alert emails (direct deposits and bill payments)."""
    parsed = None
    try:
        parsed = parse_chase_alert(bytes(msg.raw_eml))
        logger.info("✓ Parsed Chase email msg_id=%s amount=%s description='%s'",
                   msg.message_id, parsed.get("amount"), parsed.get("description", "")[:50])

        if not parsed.get("amount"):
            logger.warning("⚠️  SKIPPED msg_id=%s reason=missing_amount", msg.message_id)
            msg.processing_error = "Missing amount"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        return _create_transaction(msg, parsed)

    except IntegrityError as exc:
        return _handle_duplicate(msg, parsed, exc)


def _process_ibkr_trade(msg: UserEmailMessage) -> int:
    """Process Interactive Brokers trade confirmation emails."""
    parsed = None
    try:
        parsed = parse_ibkr_trade(bytes(msg.raw_eml))

        if not parsed:
            logger.warning("⚠️  SKIPPED msg_id=%s reason=ibkr_parse_failed", msg.message_id)
            msg.processing_error = "Failed to parse IBKR trade"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        logger.info("✓ Parsed IBKR trade msg_id=%s symbol=%s bought=%s amount=%s price=%s",
                   msg.message_id, parsed.get("symbol"), parsed.get("bought"),
                   parsed.get("amount"), parsed.get("unitprice"))

        external_id = parsed.get("external_id")

        # Check for duplicate stocks
        exists = Stock.objects.filter(user=msg.user, external_id=external_id).exists() if external_id else False
        if exists:
            logger.warning("⚠️  DUPLICATE STOCK msg_id=%s external_id=%s → moved to pending",
                          msg.message_id, external_id)
            PendingTransaction.objects.create(
                user=msg.user,
                external_id=external_id or "",
                payload=parsed,
                reason="duplicate_stock",
            )
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processed_at"])
            return 1

        # Create Transaction records (and optionally Stock)
        with transaction.atomic():
            tx_date = msg.date.date() if msg.date else date.today()
            invest_cat = _get_investments_category(msg.user)

            action = "BUY" if parsed["bought"] else "SELL"
            # For buys: positive amount (cash out), for sells: negative amount (cash in)
            cash_amount = parsed["total_value"] if parsed["bought"] else -parsed["total_value"]
            description = f"{action} {parsed['amount']} {parsed['symbol']} @ ${parsed['unitprice']}"
            forex = _is_forex(parsed["symbol"])

            if forex:
                # Forex (e.g. EUR.USD): two virtual legs — USD out, base currency in.
                # Both are virtual (internal IBKR movement).
                base_currency = parsed["symbol"].split(".")[0]   # "EUR"

                tx = Tx.objects.create(
                    user=msg.user,
                    date=tx_date,
                    description=description,
                    amount=cash_amount,
                    currency="USD",
                    source=_get_or_create_source(msg.user, "ibkr:USD"),
                    external_id=external_id,
                    status="confirmed",
                    is_virtual=True,
                    category=invest_cat,
                )

                paired_amount = -parsed["amount"] if parsed["bought"] else parsed["amount"]
                virtual_tx = Tx.objects.create(
                    user=msg.user,
                    date=tx_date,
                    description=description,
                    amount=paired_amount,
                    currency=base_currency,
                    source=_get_or_create_source(msg.user, f"ibkr:{base_currency}"),
                    external_id=external_id + ":pair" if external_id else None,
                    status="confirmed",
                    is_virtual=True,
                    paired_transaction=tx,
                    category=invest_cat,
                )
                stock = None
                logger.info(
                    "✅ CREATED forex virtual txs id=%s+%s for %s (msg_id=%s)",
                    tx.id, virtual_tx.id, description, msg.message_id
                )
            else:
                # Security buy/sell: asset leg + optional cash debit in settlement currency.
                symbol_key = _symbol_key(parsed["symbol"])       # "SUSW"
                asset_amount = -parsed["amount"] if parsed["bought"] else parsed["amount"]

                # Asset leg (virtual): ibkr:SUSW
                tx = Tx.objects.create(
                    user=msg.user,
                    date=tx_date,
                    description=description,
                    amount=asset_amount,
                    currency=symbol_key,
                    source=_get_or_create_source(msg.user, f"ibkr:{symbol_key}"),
                    external_id=external_id,
                    status="confirmed",
                    is_virtual=True,
                    category=invest_cat,
                )

                # Cash debit leg: use configured settlement currency if available
                settlement = IBKRSymbolCurrency.objects.filter(
                    user=msg.user, symbol=symbol_key
                ).first()

                if settlement:
                    settle_currency = settlement.currency
                    # Convert USD total to settlement currency using exchange rates
                    cash_usd = parsed["total_value"] if parsed["bought"] else -parsed["total_value"]
                    settle_amount = _convert_usd_to_currency(cash_usd, settle_currency, tx_date, msg.user)
                    if settle_amount is not None:
                        Tx.objects.create(
                            user=msg.user,
                            date=tx_date,
                            description=description,
                            amount=settle_amount,
                            currency=settle_currency,
                            source=_get_or_create_source(msg.user, f"ibkr:{settle_currency}"),
                            external_id=external_id + ":cash" if external_id else None,
                            status="confirmed",
                            is_virtual=True,
                            paired_transaction=tx,
                            category=invest_cat,
                        )
                        logger.info(
                            "✅ CREATED cash leg ibkr:%s amount=%s for %s (msg_id=%s)",
                            settle_currency, settle_amount, description, msg.message_id
                        )
                    else:
                        logger.warning(
                            "⚠️  No exchange rate for %s→USD, cash leg skipped for %s",
                            settle_currency, description
                        )

                stock = Stock.objects.create(
                    user=msg.user,
                    date=tx_date,
                    symbol=parsed["symbol"],
                    bought=parsed["bought"],
                    amount=parsed["amount"],
                    unitprice=parsed["unitprice"],
                    external_id=external_id,
                    transaction=tx,
                )
                logger.info(
                    "✅ CREATED stock id=%s and virtual tx id=%s for %s %s %s (msg_id=%s)",
                    stock.id, tx.id, action, parsed["amount"], parsed["symbol"], msg.message_id
                )
        msg.processed_at = timezone.now()
        msg.save(update_fields=["processed_at"])
        return 1

    except IntegrityError as exc:
        return _handle_duplicate(msg, parsed, exc)


def _process_alignet_alert(msg: UserEmailMessage) -> int:
    """Process Alignet security code emails."""
    parsed = None
    try:
        parsed = parse_alignet_alert(bytes(msg.raw_eml))
        logger.info("✓ Parsed Alignet email msg_id=%s amount=%s currency=%s description='%s'",
                   msg.message_id, parsed.get("amount"), parsed.get("currency"),
                   parsed.get("description", "")[:50])

        # Validate required fields
        if not parsed.get("amount") or not parsed.get("currency"):
            logger.warning("⚠️  SKIPPED msg_id=%s reason=missing_amount_currency", msg.message_id)
            msg.processing_error = "Missing amount or currency"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        return _create_transaction(msg, parsed)

    except IntegrityError as exc:
        return _handle_duplicate(msg, parsed, exc)


def _process_midinero_alert(msg: UserEmailMessage) -> int:
    """Process Midinero transaction alert emails."""
    parsed = None
    try:
        parsed = parse_midinero_alert(bytes(msg.raw_eml))

        if not parsed:
            logger.warning("⚠️  SKIPPED msg_id=%s reason=not_midinero_format", msg.message_id)
            msg.processing_error = "Not a recognized Midinero format"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        logger.info("✓ Parsed Midinero email msg_id=%s amount=%s currency=%s description='%s'",
                   msg.message_id, parsed.get("amount"), parsed.get("currency"),
                   parsed.get("description", "")[:50])

        # Validate required fields
        if not parsed.get("amount") or not parsed.get("currency"):
            logger.warning("⚠️  SKIPPED msg_id=%s reason=missing_amount_currency", msg.message_id)
            msg.processing_error = "Missing amount or currency"
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
            return 0

        # Override date from parsed if available
        if parsed.get("date"):
            try:
                from datetime import datetime
                parsed_date = datetime.fromisoformat(parsed["date"]).date()
                msg.date = parsed_date
            except (ValueError, TypeError):
                pass

        return _create_transaction(msg, parsed)

    except IntegrityError as exc:
        return _handle_duplicate(msg, parsed, exc)


def _maybe_create_ibkr_deposit_counterpart(user, tx: Tx) -> None:
    """If a bank transaction is an IBKR deposit, auto-create the ibkr:USD credit leg."""
    if _IBKR_DEPOSIT_MARKER not in tx.description.lower():
        return
    if tx.paired_transaction_id or tx.pair.exists():
        return  # already paired
    Tx.objects.create(
        user=user,
        date=tx.date,
        description=tx.description,
        amount=-tx.amount,
        currency=tx.currency,
        source=_get_or_create_source(user, "ibkr:USD"),
        status="confirmed",
        is_virtual=True,
        paired_transaction=tx,
        category=_get_investments_category(user),
        comments=f"Auto-created IBKR deposit counterpart for tx #{tx.pk}",
    )
    logger.info("✅ Created ibkr:USD deposit counterpart for tx id=%s", tx.pk)


def _create_transaction(msg: UserEmailMessage, parsed: dict) -> int:
    """Create a Transaction from parsed email data."""
    external_id = parsed.get("external_id")

    # Check for duplicates
    exists = Tx.objects.filter(user=msg.user, external_id=external_id).exists() if external_id else False
    if exists:
        logger.warning("⚠️  DUPLICATE msg_id=%s external_id=%s → moved to pending",
                      msg.message_id, external_id)
        PendingTransaction.objects.create(
            user=msg.user,
            external_id=external_id or "",
            payload=parsed,
            reason="duplicate",
        )
        msg.processed_at = timezone.now()
        msg.save(update_fields=["processed_at"])
        return 1

    with transaction.atomic():
        # Handle both datetime and date objects
        if msg.date:
            tx_date = msg.date.date() if isinstance(msg.date, datetime_class) else msg.date
        else:
            tx_date = date.today()
        tx = Tx.objects.create(
            user=msg.user,
            date=tx_date,
            description=parsed.get("description") or "",
            amount=parsed.get("amount"),
            currency=(parsed.get("currency") or "").upper(),
            source=_get_or_create_source(msg.user, parsed.get("source")),
            comments=parsed.get("comments") or "",
            external_id=external_id,
            status="confirmed",
        )
    _maybe_create_ibkr_deposit_counterpart(msg.user, tx)
    logger.info(
        "✅ CREATED transaction id=%s amount=%s %s description='%s' (msg_id=%s)",
        tx.id, tx.amount, tx.currency, tx.description[:50], msg.message_id
    )
    msg.processed_at = timezone.now()
    msg.save(update_fields=["processed_at"])
    return 1


def _handle_duplicate(msg: UserEmailMessage, parsed: Optional[dict], exc: IntegrityError) -> int:
    """Handle duplicate transaction/stock errors."""
    logger.warning(
        "⚠️  INTEGRITY ERROR msg_id=%s external_id=%s → moved to pending. Error: %s",
        msg.message_id,
        parsed.get("external_id") if parsed else None,
        str(exc)[:200],
    )
    if parsed:
        PendingTransaction.objects.create(
            user=msg.user,
            external_id=parsed.get("external_id") or "",
            payload=parsed,
            reason="duplicate",
        )
    msg.processed_at = timezone.now()
    msg.save(update_fields=["processed_at"])
    return 1
