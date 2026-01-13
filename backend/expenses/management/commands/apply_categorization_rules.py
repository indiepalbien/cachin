"""
Management command to apply categorization rules to uncategorized transactions.

Usage:
    python manage.py apply_categorization_rules [--user=<username>] [--max=<count>]
    
Examples:
    # Apply rules for current user
    python manage.py apply_categorization_rules --user=alice
    
    # Apply rules to max 100 transactions
    python manage.py apply_categorization_rules --user=bob --max=100
    
    # Apply rules to all users
    python manage.py apply_categorization_rules
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from expenses.rule_engine import apply_rules_to_all_transactions, get_user_rule_stats

User = get_user_model()


class Command(BaseCommand):
    help = 'Apply categorization rules to uncategorized transactions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Username to process (if not provided, processes all users)',
        )
        parser.add_argument(
            '--max',
            type=int,
            help='Maximum number of transactions to process per user',
        )

    def handle(self, *args, **options):
        username = options.get('user')
        max_tx = options.get('max')

        users = []
        if username:
            try:
                users = [User.objects.get(username=username)]
            except User.DoesNotExist:
                raise CommandError(f'User "{username}" does not exist')
        else:
            users = User.objects.all()

        total_updated = 0
        total_processed = 0

        for user in users:
            self.stdout.write(f'\nProcessing user: {user.username}')
            
            # Get rule stats before
            stats_before = get_user_rule_stats(user)
            self.stdout.write(f'  Rules: {stats_before["total_rules"]}')
            self.stdout.write(f'  Total applications: {stats_before["total_applications"]}')
            
            # Apply rules
            updated, total = apply_rules_to_all_transactions(user, max_transactions=max_tx)
            
            total_updated += updated
            total_processed += total
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Updated {updated}/{total} transactions'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nTotal: Updated {total_updated}/{total_processed} transactions'
            )
        )
