import logging
from datetime import datetime

from celery import shared_task
from django.conf import settings
import requests
from decimal import Decimal
from .models import DefaultExchangeRate
import logging

logger = logging.getLogger(__name__)

# List of common currencies for Latin America, Europe, and North America
COMMON_CURRENCIES = [
    # North America
    'USD', 'CAD', 'MXN',
    # Latin America
    'UYU', 'ARS', 'BRL', 'CLP', 'COP', 'PEN', 'VES', 'PYG',
    # Europe
    'EUR', 'GBP', 'CHF', 'SEK', 'NOK', 'DKK', 'PLN',
]

@shared_task
def update_exchange_rates():
    """Fetch exchange rates from openexchangerates.org and update defaults."""
    api_key = settings.OPENEXCHANGERATES_API_KEY
    if not api_key:
        logger.error("OPENEXCHANGERATES_API_KEY not configured")
        return
    
    try:
        url = f'https://openexchangerates.org/api/latest.json?app_id={api_key}&base=USD'
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'rates' not in data:
            logger.error(f"Invalid response from openexchangerates: {data}")
            return
        
        rates = data['rates']
        updated_count = 0
        
        for currency in COMMON_CURRENCIES:
            if currency in rates:
                rate = Decimal(str(rates[currency]))
                obj, created = DefaultExchangeRate.objects.update_or_create(
                    currency=currency,
                    defaults={'rate': rate}
                )
                updated_count += 1
                logger.info(f"Updated {currency}: {rate}")
        
        logger.info(f"Successfully updated {updated_count} exchange rates")
        
    except requests.RequestException as e:
        logger.error(f"Error fetching exchange rates: {e}")
    except Exception as e:
        logger.error(f"Unexpected error updating exchange rates: {e}")
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
        logger.info(f"Found {len(groups)} Splitwise groups: {groups_map}")

        # Get recent expenses (last 100)
        expenses = sObj.getExpenses(limit=100)
        logger.info(f"Fetched {len(expenses)} Splitwise expenses")

    except Exception:
        logger.exception("Error fetching Splitwise data for user %s", user_id)
        return

    transactions_created = 0
    transactions_updated = 0
    skipped_no_share = 0
    skipped_zero_amount = 0

    for expense in expenses:
        try:
            expense_id = expense.getId()
            external_id = f"splitwise:{expense_id}"
            description = expense.getDescription() or 'Splitwise'

            # Get group info for logging
            group_id = expense.getGroupId()
            group_name = groups_map.get(group_id, 'Unknown') if group_id and group_id != 0 else 'non-group'

            # Find current user's share
            user_share = None
            for user in expense.getUsers():
                if user.getId() == current_user_id:
                    user_share = user
                    break

            if not user_share:
                logger.info(f"[SKIP] Expense {expense_id} ({description}) from {group_name}: user not participant")
                skipped_no_share += 1
                continue

            # Get net balance (amount user owes or is owed)
            # Positive net_balance in Splitwise = user owes/paid (expense) = should be NEGATIVE in our app
            # Negative net_balance in Splitwise = user is owed (income) = should be POSITIVE in our app
            net_balance = float(user_share.getNetBalance())
            amount = Decimal(str(-net_balance))  # Invert sign

            # Skip if amount is zero
            if amount == 0:
                logger.info(f"[SKIP] Expense {expense_id} ({description}) from {group_name}: zero net balance")
                skipped_zero_amount += 1
                continue

            logger.info(f"[PROCESS] Expense {expense_id} ({description}) from {group_name}: amount={amount}, net_balance={net_balance}")

            currency = expense.getCurrencyCode() or 'USD'

            # Get group name from group_id
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
                        'source': source_obj,
                    }
                )
                if created:
                    transactions_created += 1
                    logger.info(f"[CREATE] Transaction {external_id} created: {description} - {amount} {currency}")
                else:
                    updated = False
                    changes = []

                    # Compare amount (normalize Decimals to 2 decimal places)
                    if tx.amount.quantize(Decimal('0.01')) != amount.quantize(Decimal('0.01')):
                        old_amount = tx.amount
                        tx.amount = amount
                        updated = True
                        changes.append(f"amount: {old_amount} -> {amount}")

                    # Compare description
                    if tx.description != description:
                        old_desc = tx.description
                        tx.description = description
                        updated = True
                        changes.append(f"description: {old_desc} -> {description}")

                    # Compare source by ID, not object identity
                    if tx.source_id != source_obj.id:
                        old_source = tx.source
                        tx.source = source_obj
                        updated = True
                        changes.append(f"source: {old_source} -> {source_obj}")

                    # Compare currency
                    if tx.currency != currency:
                        old_currency = tx.currency
                        tx.currency = currency
                        updated = True
                        changes.append(f"currency: {old_currency} -> {currency}")

                    if updated:
                        transactions_updated += 1
                        tx.save()
                        logger.info(f"[UPDATE] Transaction {external_id} updated: {', '.join(changes)}")
                    else:
                        logger.debug(f"[SKIP] Transaction {external_id} unchanged")
            except Exception:
                logger.exception(f"Transaction error for expense {expense_id}")

        except Exception:
            logger.exception("Error procesando expense %s", expense_id)

    account.last_synced = timezone.now()
    account.save()

    logger.info(
        f"Splitwise sync for user {account.user.username} (ID: {user_id}) COMPLETE: "
        f"{transactions_created} created, {transactions_updated} updated, "
        f"{skipped_zero_amount} skipped (zero amount), {skipped_no_share} skipped (not participant)"
    )
    
    return {
        'user_id': user_id,
        'username': account.user.username,
        'created': transactions_created,
        'updated': transactions_updated
    }

@shared_task
def sync_all_splitwise():
    ids = list(SplitwiseAccount.objects.values_list('user_id', flat=True))
    logger.info(f"Starting Splitwise sync for {len(ids)} users")
    
    total_created = 0
    total_updated = 0
    results = []
    
    for uid in ids:
        result = sync_splitwise_for_user(uid)
        if result:
            results.append(result)
            total_created += result.get('created', 0)
            total_updated += result.get('updated', 0)
    
    logger.info(
        f"Splitwise sync completed: {len(results)} users processed, "
        f"{total_created} total new transactions, {total_updated} total updated"
    )
    
    for result in results:
        logger.debug(
            f"  - {result['username']}: {result['created']} new, {result['updated']} updated"
        )


# ============================================================================
# Intelligent Categorization Rules Tasks
# ============================================================================

@shared_task
def apply_categorization_rules_for_user(user_id, max_transactions=None):
    """
    Apply categorization rules to uncategorized transactions for a specific user.
    
    This task:
    1. Finds all uncategorized transactions
    2. Tries to match them with existing rules
    3. Applies the best matching rule automatically
    
    Args:
        user_id: ID of the user
        max_transactions: Maximum number of transactions to process (None = all)
    """
    from django.contrib.auth import get_user_model
    from .rule_engine import apply_rules_to_all_transactions
    
    try:
        User = get_user_model()
        user = User.objects.get(id=user_id)
        
        updated, total = apply_rules_to_all_transactions(user, max_transactions=max_transactions)
        
        logger.info(
            f"Categorization rules applied for user {user.username}: "
            f"{updated}/{total} transactions categorized"
        )
        
        return {
            'user_id': user_id,
            'updated': updated,
            'total': total,
            'success': True
        }
    except Exception as e:
        logger.error(f"Error applying categorization rules for user {user_id}: {e}")
        return {
            'user_id': user_id,
            'success': False,
            'error': str(e)
        }


@shared_task
def apply_categorization_rules_all_users(max_transactions_per_user=None):
    """
    Apply categorization rules to all users.
    
    This task spawns individual tasks for each user to parallelize processing.
    
    Args:
        max_transactions_per_user: Max transactions per user (None = all)
    """
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    user_ids = list(User.objects.values_list('id', flat=True))
    
    logger.info(f"Starting categorization rules for {len(user_ids)} users")
    
    # Spawn individual tasks for each user
    for user_id in user_ids:
        apply_categorization_rules_for_user.delay(
            user_id,
            max_transactions=max_transactions_per_user
        )
    
    return {
        'total_users': len(user_ids),
        'tasks_spawned': len(user_ids)
    }