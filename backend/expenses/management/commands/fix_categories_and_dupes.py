"""
One-shot fix:
1. Set all IBKR virtual txs to category='investments'
2. Delete duplicate Uber transaction (content-based)
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fix IBKR categories and remove Uber duplicates"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--user-id", type=int, default=7)

    def handle(self, *args, **options):
        from expenses.models import Category, Transaction
        dry_run = options["dry_run"]
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))

        # 1. Fix IBKR categories
        cat, _ = Category.objects.get_or_create(
            user_id=user_id, name="investments",
            defaults={"counts_to_total": False},
        )
        ibkr_txs = Transaction.objects.filter(
            user_id=user_id,
            source__name__startswith="ibkr:",
            is_virtual=True,
        ).exclude(category=cat)
        self.stdout.write(f"\n=== IBKR TXS TO RE-CATEGORIZE: {ibkr_txs.count()} ===\n")
        for t in ibkr_txs[:5]:
            old_cat = t.category.name if t.category else "None"
            self.stdout.write(f"  tx={t.id} {old_cat} → investments\n")
        if ibkr_txs.count() > 5:
            self.stdout.write(f"  ... and {ibkr_txs.count() - 5} more\n")
        if not dry_run:
            updated = ibkr_txs.update(category=cat)
            self.stdout.write(self.style.SUCCESS(f"  Updated {updated} IBKR txs\n"))

        # 2. Find and remove content-based duplicates
        self.stdout.write(f"\n=== CONTENT DUPLICATES ===\n")
        from django.db.models import Count
        dupes = (
            Transaction.objects.filter(user_id=user_id, is_virtual=False)
            .values("date", "description", "amount", "currency")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        deleted = 0
        for d in dupes:
            txs = list(
                Transaction.objects.filter(
                    user_id=user_id,
                    date=d["date"],
                    description=d["description"],
                    amount=d["amount"],
                    currency=d["currency"],
                    is_virtual=False,
                ).order_by("id")
            )
            keep = txs[0]
            for dup in txs[1:]:
                self.stdout.write(
                    f"  DELETE tx id={dup.id} '{dup.description[:40]}' {dup.amount} {dup.currency} "
                    f"on {dup.date} (keeping tx id={keep.id})\n"
                )
                if not dry_run:
                    dup.delete()
                    deleted += 1

        self.stdout.write(f"\nDeleted {deleted} duplicate txs\n")
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
