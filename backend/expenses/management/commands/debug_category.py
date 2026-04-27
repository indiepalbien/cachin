"""Show all transactions in a specific category for a given month."""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show transactions contributing to a category total"

    def add_arguments(self, parser):
        parser.add_argument("category", type=str)
        parser.add_argument("--user-id", type=int, default=7)
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--month", type=int, default=4)

    def handle(self, *args, **options):
        from expenses.models import Category, Transaction

        user_id = options["user_id"]
        cat_name = options["category"]
        year = options["year"]
        month = options["month"]

        cat = Category.objects.filter(user_id=user_id, name__iexact=cat_name).first()
        if not cat:
            self.stdout.write(f"Category '{cat_name}' not found\n")
            return

        self.stdout.write(f"Category: '{cat.name}' (id={cat.id}, counts_to_total={cat.counts_to_total})\n\n")

        first = datetime.date(year, month, 1)
        ny = year + (month // 12)
        nm = (month % 12) + 1
        last = datetime.date(ny, nm, 1)

        # Non-virtual, non-reimbursable txs in this month with this category
        txs = Transaction.objects.filter(
            user_id=user_id,
            category=cat,
            date__gte=first,
            date__lt=last,
            is_virtual=False,
            is_reimbursable=False,
        ).order_by("date").select_related("source")

        total = Decimal("0")
        total_usd = Decimal("0")

        self.stdout.write(f"=== {year}-{month:02d} non-virtual txs in '{cat_name}' ===\n")
        for t in txs:
            usd = t.to_usd()
            usd_str = f"${usd:.2f}" if usd is not None else "?"
            total += t.amount
            if usd is not None:
                total_usd += usd
            self.stdout.write(
                f"  id={t.id:5d} {t.date} {t.amount:>10.2f} {t.currency:<5s} "
                f"→ {usd_str:>10s} USD  src={t.source.name if t.source else '—':<20s} "
                f"'{t.description[:45]}'\n"
            )

        self.stdout.write(f"\nTotal: {total:.2f} (native) / ${total_usd:.2f} (USD)\n")
        self.stdout.write(f"Count: {txs.count()} txs\n")

        # Also show virtual ones in this category (should not contribute to total)
        vtxs = Transaction.objects.filter(
            user_id=user_id,
            category=cat,
            date__gte=first,
            date__lt=last,
            is_virtual=True,
        ).count()
        self.stdout.write(f"\nVirtual txs in this category (excluded from total): {vtxs}\n")
