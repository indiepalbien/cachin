#!/usr/bin/env python
"""Debug script to run Splitwise sync and show output"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'misfinanzas.settings')
django.setup()

from expenses.tasks import sync_splitwise_for_user
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.first()

print(f"=" * 80)
print(f"Running Splitwise sync for user: {user.username} (ID: {user.id})")
print(f"=" * 80)

result = sync_splitwise_for_user(user.id)

print(f"\n" + "=" * 80)
print("SYNC RESULT:")
print(result)
print("=" * 80)
