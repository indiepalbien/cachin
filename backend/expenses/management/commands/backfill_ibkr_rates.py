"""
Backfill exchange rates from IBKR forex trade descriptions.

Scans virtual IBKR forex transactions (symbol like EUR.USD) and creates
Exchange rate records for the trade date if none exist.
"""
from decimal import Decimal
import re

from django.core.management.base import BaseCommand

from expenses.models import Exchange, Transaction


_FOREX_DESC = re.compile(r'(BUY|SELL)\s+([\d,]+\.?\d*)\s+([A-Z]{3})\.([A-Z]{3})\s+@\s+\$?([\d,]+\.?\d+)', re.I)


class Command(BaseCommand):
    help = "Backfill Exchange rates from IBKR virtual forex transactions"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--user-id", type=int, default=None)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))

        qs = Transaction.objects.filter(
            is_virtual=True,
            source__name__startswith="ibkr:",
        ).select_related("user", "source")

        if user_id:
            qs = qs.filter(user_id=user_id)

        created = 0
        skipped = 0

        for tx in qs:
            m = _FOREX_DESC.search(tx.description)
            if not m:
                continue

            base_currency = m.group(3).upper()   # EUR
            quote_currency = m.group(4).upper()  # USD
            rate_str = m.group(5).replace(",", "")
            rate = Decimal(rate_str)

            # rate = how many quote_currency per 1 base_currency
            # i.e. EUR.USD @ 1.1697 means 1 EUR = 1.1697 USD
            # Store as: source=base, target=quote, rate=rate
            exists = Exchange.objects.filter(
                user=tx.user,
                source_currency__iexact=base_currency,
                target_currency__iexact=quote_currency,
                date=tx.date,
            ).exists()

            if exists:
                self.stdout.write(
                    f"  SKIP existing rate {base_currency}→{quote_currency} on {tx.date} "
                    f"(user={tx.user_id})\n"
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  CREATE rate {base_currency}→{quote_currency} = {rate} on {tx.date} "
                f"(user={tx.user_id}, from tx id={tx.id})\n"
            )
            if not dry_run:
                Exchange.objects.create(
                    user=tx.user,
                    date=tx.date,
                    source_currency=base_currency,
                    target_currency=quote_currency,
                    rate=rate,
                )
                created += 1

        self.stdout.write(f"\nSummary: {created} rates created, {skipped} skipped\n")
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes saved ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
