import logging
from datetime import datetime

from celery import shared_task
from django.core.management import call_command

from expenses.email_ingest import process_new_messages
from .models import SplitwiseAccount
from splitwise import Splitwise
from django.utils import timezone
from decimal import Decimal
from django.conf import settings


logger = logging.getLogger(__name__)


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

    try:
        # Initialize Splitwise client
        sObj = Splitwise(
            settings.SPLITWISE_CONSUMER_KEY,
            settings.SPLITWISE_CONSUMER_SECRET
        )
        sObj.setAccessToken({
            'oauth_token': account.oauth_token,
            'oauth_token_secret': account.oauth_token_secret
        })
        
        # Get current user info
        current_user = sObj.getCurrentUser()
        current_user_id = current_user.getId()
        
        # Get all groups and create a mapping
        groups = sObj.getGroups()
        groups_map = {group.getId(): group.getName() for group in groups}
        
        # Get recent expenses (last 100)
        expenses = sObj.getExpenses(limit=100)
        
    except Exception:
        logger.exception("Error fetching Splitwise data for user %s", user_id)
        return

    for expense in expenses:
        try:
            expense_id = expense.getId()
            external_id = f"splitwise:{expense_id}"
            
            # Find current user's share
            user_share = None
            for user in expense.getUsers():
                if user.getId() == current_user_id:
                    user_share = user
                    break
            
            if not user_share:
                continue
            
            # Get net balance (amount user owes or is owed)
            net_balance = float(user_share.getNetBalance())
            amount = abs(Decimal(str(net_balance)))
            
            # Skip if amount is zero
            if amount == 0:
                continue

            description = expense.getDescription() or 'Splitwise'
            currency = expense.getCurrencyCode() or 'USD'
            
            # Get group name from group_id
            group_id = expense.getGroupId()
            if group_id and group_id != 0:
                source_name = groups_map.get(group_id, 'Unknown')
                source = f"split:{source_name}"
            else:
                # For non-group expenses, use the other person's name
                other_user_name = None
                for user in expense.getUsers():
                    if user.getId() != current_user_id:
                        first = user.getFirstName() or ''
                        last = user.getLastName() or ''
                        other_user_name = f"{first} {last}".strip()
                        if not other_user_name:
                            email = user.getEmail() or 'Unknown'
                            other_user_name = email.split('@')[0]
                        break
                
                source = f"split:{other_user_name or 'personal'}"

            # Parse date
            expense_date = expense.getDate()
            if expense_date:
                try:
                    date = datetime.strptime(expense_date, "%Y-%m-%dT%H:%M:%SZ").date()
                except (ValueError, TypeError):
                    date = timezone.now().date()
            else:
                date = timezone.now().date()

            try:
                from .models import Transaction, Source
                
                # Get or create Source instance
                source_obj, _ = Source.objects.get_or_create(
                    user_id=user_id,
                    name=source
                )
                
                tx, created = Transaction.objects.get_or_create(
                    external_id=external_id,
                    defaults={
                        'user_id': user_id,
                        'amount': amount,
                        'description': description,
                        'currency': currency,
                        'date': date,
                    }
                )
                if not created:
                    updated = False
                    if tx.amount != amount:
                        tx.amount = amount; updated = True
                    if tx.description != description:
                        tx.description = description; updated = True
                    if tx.source != source_obj:
                        tx.source = source_obj; updated = True
                    if tx.currency != currency:
                        tx.currency = currency; updated = True
                    if updated:
                        tx.save()
            except Exception:
                logger.debug("Transaction model ausente o error creando tx", exc_info=True)

        except Exception:
            logger.exception("Error procesando expense %s", expense_id)

    account.last_synced = timezone.now()
    account.save()

@shared_task
def sync_all_splitwise():
    ids = list(SplitwiseAccount.objects.values_list('user_id', flat=True))
    for uid in ids:
        sync_splitwise_for_user.delay(uid)