import secrets
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .models import UserEmailConfig, Transaction, UserProfile, Category, Project
from .default_config import DEFAULT_CATEGORIES, DEFAULT_PROJECTS


def _generate_alias_localpart() -> str:
    # 16 hex chars for readability
    return secrets.token_hex(8)


@receiver(post_save, sender=get_user_model())
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile with default onboarding step when user is created."""
    if not created:
        return
    if not UserProfile.objects.filter(user=instance).exists():
        UserProfile.objects.create(user=instance, onboarding_step=1)


@receiver(post_save, sender=get_user_model())
def create_user_email_config(sender, instance, created, **kwargs):
    if not created:
        return
    # Create a config only if none exists
    if not UserEmailConfig.objects.filter(user=instance).exists():
        alias = _generate_alias_localpart()
        UserEmailConfig.objects.create(user=instance, alias_localpart=alias)


@receiver(post_save, sender=get_user_model())
def create_default_categories_and_projects(sender, instance, created, **kwargs):
    """Create default categories and projects for new users."""
    if not created:
        return
    
    # Create default categories
    for cat_data in DEFAULT_CATEGORIES:
        Category.objects.create(
            user=instance,
            name=cat_data["name"],
            counts_to_total=cat_data["counts_to_total"],
            description=cat_data["description"]
        )
    
    # Create default projects
    for proj_data in DEFAULT_PROJECTS:
        Project.objects.create(
            user=instance,
            name=proj_data["name"],
            description=proj_data["description"]
        )


@receiver(post_save, sender=Transaction)
def create_categorization_rules(sender, instance, created, update_fields, **kwargs):
    """
    When a transaction is categorized, create smart categorization rules.
    
    Rules are generated when:
    - An existing transaction's category is updated
    - An existing transaction's payee is updated
    
    Handles cases where user assigns:
    - Only category (payee stays None)
    - Only payee (category stays None)
    - Both (different transactions)
    
    Then immediately spawns a Celery task to apply rules to other transactions.
    """
    # Avoid circular imports
    from .rule_engine import generate_categorization_rules
    from .tasks import apply_categorization_rules_for_user
    
    # Skip if this is a new transaction (prefer explicit rule creation in views)
    if created:
        return
    
    # Skip if update_fields is None (means all fields were updated, happens in some cases)
    if update_fields is None:
        return
    
    # Check if category or payee was updated
    is_category_update = 'category' in update_fields
    is_payee_update = 'payee' in update_fields
    
    # If neither category nor payee was updated, skip
    if not (is_category_update or is_payee_update):
        return
    
    # Skip if both category AND payee are None (nothing assigned)
    if not instance.category and not instance.payee:
        return
    
    # Generate rules for this categorization
    # - If only category is assigned: creates rules for category
    # - If only payee is assigned: creates rules for payee
    # - If both: creates rules for both
    generate_categorization_rules(
        user=instance.user,
        description=instance.description,
        amount=instance.amount,
        currency=instance.currency,
        category=instance.category,
        payee=instance.payee,
    )
    
    # Immediately spawn Celery task to apply rules to other uncategorized transactions
    # This happens asynchronously so it doesn't block the response
    try:
        apply_categorization_rules_for_user.delay(
            user_id=instance.user.id,
            max_transactions=50  # Process up to 50 transactions per categorization
        )
    except Exception as e:
        # If Celery/Redis isn't running (e.g., local development), just skip the background task
        # The rules were still created above, they just won't be applied automatically
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to queue categorization task (Redis/Celery not available): {e}")