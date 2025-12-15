import logging
from datetime import date
from email.utils import parseaddr
from typing import Optional

from django.db import transaction, IntegrityError
from django.utils import timezone

from expenses.email_parsers.visa import parse_visa_alert
from expenses.models import (
    PendingTransaction,
    Source,
    Transaction as Tx,
    UserEmailMessage,
)


logger = logging.getLogger(__name__)


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
            parsed = parse_visa_alert(bytes(msg.raw_eml))

            # Gate by sender: allow direct sender, forwarded, or body mention
            allowed_sender = "donotreplyalertadecomprasvisa@visa.com"
            envelope_from = parseaddr(msg.from_address or "")[1].lower()
            parsed_froms = parsed.get("from_emails") or []
            body = (parsed.get("raw_body") or "").lower()
            logger.info(
                "ingest msg_id=%s envelope_from=%s parsed_froms=%s allowed=%s",
                msg.message_id,
                envelope_from,
                parsed_froms,
                allowed_sender,
            )
            if not (
                envelope_from == allowed_sender
                or allowed_sender in parsed_froms
                or allowed_sender in body
            ):
                logger.info(
                    "skip msg_id=%s reason=sender_mismatch body_contains=%s",
                    msg.message_id,
                    allowed_sender in body,
                )
                msg.processing_error = "skipped_non_visa_sender"
                msg.processed_at = timezone.now()
                msg.save(update_fields=["processing_error", "processed_at"])
                continue
            if not parsed.get("amount") or not parsed.get("currency"):
                logger.info(
                    "skip msg_id=%s reason=missing_amount_currency parsed=%s",
                    msg.message_id,
                    {k: parsed.get(k) for k in ("amount", "currency")},
                )
                msg.processing_error = "Missing amount or currency"
                msg.processed_at = timezone.now()
                msg.save(update_fields=["processing_error", "processed_at"])
                continue

            external_id = parsed.get("external_id")
            # if external_id already exists for user, push to pending
            exists = Tx.objects.filter(user=msg.user, external_id=external_id).exists() if external_id else False
            if exists:
                logger.info(
                    "pending duplicate msg_id=%s external_id=%s user=%s",
                    msg.message_id,
                    external_id,
                    msg.user_id,
                )
                PendingTransaction.objects.create(
                    user=msg.user,
                    external_id=external_id or "",
                    payload=parsed,
                    reason="duplicate",
                )
                msg.processed_at = timezone.now()
                msg.save(update_fields=["processed_at"])
                count += 1
                continue

            with transaction.atomic():
                tx_date = msg.date.date() if msg.date else date.today()
                tx = Tx.objects.create(
                    user=msg.user,
                    date=tx_date,
                    description=parsed.get("description") or "",
                    amount=parsed.get("amount"),
                    currency=(parsed.get("currency") or "").upper(),
                    source=_get_or_create_source(msg.user, parsed.get("source")),
                    external_id=external_id,
                    status="confirmed",
                )
            logger.info(
                "created tx id=%s msg_id=%s external_id=%s user=%s",
                tx.id,
                msg.message_id,
                external_id,
                msg.user_id,
            )
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processed_at"])
            count += 1
        except IntegrityError:
            logger.info(
                "integrity duplicate msg_id=%s external_id=%s user=%s",
                msg.message_id,
                parsed.get("external_id") if 'parsed' in locals() else None,
                msg.user_id,
            )
            PendingTransaction.objects.create(
                user=msg.user,
                external_id=parsed.get("external_id") or "",
                payload=parsed,
                reason="duplicate",
            )
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processed_at"])
            count += 1
        except Exception as exc:  # broad: log error and continue
            logger.exception("error processing msg_id=%s", msg.message_id)
            msg.processing_error = str(exc)
            msg.processed_at = timezone.now()
            msg.save(update_fields=["processing_error", "processed_at"])
    return count
