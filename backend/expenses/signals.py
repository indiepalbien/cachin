import secrets
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .models import UserEmailConfig


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