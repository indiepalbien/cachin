import secrets
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .models import UserEmailConfig, Transaction


def _generate_alias_localpart() -> str:
    # 16 hex chars for readability
    return secrets.token_hex(8)


@receiver(post_save, sender=get_user_model())
def create_user_email_config(sender, instance, created, **kwargs):
    if not created:
        return
    # Create a config only if none exists
    if not UserEmailConfig.objects.filter(user=instance).exists():
        alias = _generate_alias_localpart()
        UserEmailConfig.objects.create(user=instance, alias_localpart=alias)


@receiver(post_save, sender=Transaction)
def create_categorization_rules(sender, instance, created, update_fields, **kwargs):
    """
    When a transaction is categorized, create smart categorization rules.
    
    Rules are generated when:
    - A new transaction is saved with category/payee
    - An existing transaction's category/payee is updated
    """
    # Avoid circular imports
    from .rule_engine import generate_categorization_rules
    
    # Skip if this is a new transaction (prefer explicit rule creation in views)
    # or if we don't have a meaningful categorization
    if created:
        return
    
    # Check if category or payee was updated
    is_category_update = update_fields and 'category' in update_fields
    is_payee_update = update_fields and 'payee' in update_fields
    
    # If neither category nor payee was updated, skip
    if not (is_category_update or is_payee_update):
        return
    
    # Only create rules if we have a category or payee assigned
    if not instance.category and not instance.payee:
        return
    
    # Generate rules for this categorization
    generate_categorization_rules(
        user=instance.user,
        description=instance.description,
        amount=instance.amount,
        currency=instance.currency,
        category=instance.category,
        payee=instance.payee,
    )