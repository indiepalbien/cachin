"""Management command to recalculate amount_usd for all existing transactions."""
from django.core.management.base import BaseCommand
from expenses.models import Transaction


class Command(BaseCommand):
    help = "Recalculate amount_usd for all existing transactions"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually updating',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        transactions = Transaction.objects.all()
        total = transactions.count()
        updated = 0
        missing_rates = 0
        
        self.stdout.write(f"Processing {total} transactions...")
        
        for i, tx in enumerate(transactions.iterator(), 1):
            if i % 100 == 0:
                self.stdout.write(f"  Processed {i}/{total}...")
            
            # Calculate USD amount
            usd_amount = tx._calculate_usd()
            
            if usd_amount is None:
                missing_rates += 1
            
            if not dry_run and tx.amount_usd != usd_amount:
                tx.amount_usd = usd_amount
                # Use update_fields to avoid triggering save() logic again
                tx.save(update_fields=['amount_usd'])
                updated += 1
            elif dry_run and tx.amount_usd != usd_amount:
                updated += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY RUN] Would update {updated} transactions"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ Updated {updated} transactions with USD amounts"
                )
            )
        
        if missing_rates > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  {missing_rates} transactions are missing exchange rates"
                )
            )
