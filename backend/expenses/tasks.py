import logging

from celery import shared_task
from django.core.management import call_command

from expenses.email_ingest import process_new_messages
from .models import SplitwiseAccount
import requests
from requests_oauthlib import OAuth1
from django.utils import timezone
from decimal import Decimal
from django.conf import settings


logger = logging.getLogger(__name__)
API_BASE = 'https://secure.splitwise.com/api/v3.0'


@shared_task
def fetch_emails_task():
    logger.info("Starting fetch_emails task")
    call_command('fetch_emails')
    processed = process_new_messages()
    logger.info("Finished fetch_emails task; processed %s messages", processed)


@shared_task
def sync_splitwise_for_user(user_id):
    try:
        account = SplitwiseAccount.objects.get(user_id=user_id)
    except SplitwiseAccount.DoesNotExist:
        return
    if not account.oauth_token or not account.oauth_token_secret:
        return

    auth = OAuth1(settings.SPLITWISE_CONSUMER_KEY,
                  client_secret=settings.SPLITWISE_CONSUMER_SECRET,
                  resource_owner_key=account.oauth_token,
                  resource_owner_secret=account.oauth_token_secret)

    try:
        resp = requests.get(f'{API_BASE}/get_expenses', auth=auth, params={'limit': 100}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        logger.exception("Error fetching Splitwise expenses for user %s", user_id)
        return

    expenses = payload.get('expenses', []) or []
    for e in expenses:
        try:
            expense_id = e.get('id') or e.get('expense_id')
            external_id = f"splitwise:{expense_id}"
            user_entry = None
            for u in e.get('users', []):
                if str(u.get('user_id') or u.get('id')) == str(account.splitwise_user_id):
                    user_entry = u
                    break
            if not user_entry:
                continue

            owed = Decimal(str(user_entry.get('owed_share') or '0'))
            paid_share = Decimal(str(user_entry.get('paid_share') or '0'))
            amount = None
            if owed > paid_share:
                amount = owed
            elif paid_share > owed:
                amount = paid_share - owed
            else:
                continue

            description = e.get('description') or e.get('details') or 'Splitwise'
            group = (e.get('group') or {}).get('name') or (e.get('group_name') or '')
            if group:
                source = f"split:{group}"
            else:
                first_user = (e.get('users') or [])[0] or {}
                source = f"split:{first_user.get('name') or 'splitwise'}"

            try:
                from .models import Transaction
                tx, created = Transaction.objects.get_or_create(
                    external_id=external_id,
                    defaults={
                        'user_id': user_id,
                        'amount': amount,
                        'description': description,
                        'source': source,
                        'date': e.get('date') or timezone.now().date(),
                    }
                )
                if not created:
                    updated = False
                    if tx.amount != amount:
                        tx.amount = amount; updated = True
                    if tx.description != description:
                        tx.description = description; updated = True
                    if tx.source != source:
                        tx.source = source; updated = True
                    if updated:
                        tx.save()
            except Exception:
                logger.debug("Transaction model ausente o error creando tx", exc_info=True)

        except Exception:
            logger.exception("Error procesando expense %s", e.get('id'))

    account.last_synced = timezone.now()
    account.save()

@shared_task
def sync_all_splitwise():
    ids = list(SplitwiseAccount.objects.values_list('user_id', flat=True))
    for uid in ids:
        sync_splitwise_for_user.delay(uid)