"""
One-time migration: fix existing IBKR primary transactions to match new schema.

New schema:
- Security trades: only a single virtual tx on ibkr:SYMBOL (no USD cash leg)
- Forex trades: two virtual txs (ibkr:USD + ibkr:BASE_CURRENCY)

Existing data after first backfill:
- Security trades: primary non-virtual tx on ibkr:USD  +  virtual tx on ibkr:SYMBOL
- Forex trades: primary non-virtual tx on ibkr:USD  +  virtual tx on ibkr:BASE

Fix:
- Security primary txs (linked via Stock): DELETE them (the virtual asset leg is correct)
- Forex primary txs: mark is_virtual=True (both legs should be virtual)
- Update Stock.transaction FK to point to the asset-leg virtual tx

Run with --dry-run first.
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from expenses.models import Stock, Transaction
from expenses.email_ingest import _is_forex


class Command(BaseCommand):
    help = "Fix existing IBKR primary transactions to match new schema"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--since", default="2026-04-01")
        parser.add_argument("--user-id", type=int, default=None)

    def handle(self, *args, **options):
        import datetime
        dry_run = options["dry_run"]
        since = datetime.date.fromisoformat(options["since"])
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))

        stocks_qs = (
            Stock.objects
            .filter(date__gte=since)
            .select_related("transaction", "transaction__source", "transaction__user")
        )
        if user_id:
            stocks_qs = stocks_qs.filter(user_id=user_id)

        deleted = 0
        made_virtual = 0
        stock_relinked = 0

        for stock in stocks_qs:
            tx = stock.transaction
            if tx is None:
                continue

            forex = _is_forex(stock.symbol)

            if forex:
                # Forex: primary tx should be virtual
                if not tx.is_virtual:
                    self.stdout.write(
                        f"  FOREX mark virtual: tx id={tx.id} '{tx.description[:60]}'\n"
                    )
                    if not dry_run:
                        tx.is_virtual = True
                        tx.save(update_fields=["is_virtual"])
                    made_virtual += 1
                else:
                    self.stdout.write(f"  FOREX already virtual: tx id={tx.id}\n")
            else:
                # Security: primary USD tx should be deleted; asset-leg virtual tx is correct.
                # Find the paired virtual asset-leg tx to relink Stock.
                asset_leg = tx.pair.filter(is_virtual=True).first()

                self.stdout.write(
                    f"  SECURITY delete primary tx id={tx.id} '{tx.description[:60]}' "
                    f"(amount={tx.amount} {tx.currency})"
                )
                if asset_leg:
                    self.stdout.write(f" → relink Stock id={stock.id} to tx id={asset_leg.id}\n")
                else:
                    self.stdout.write(f" → NO asset leg found, Stock id={stock.id} will lose tx link\n")

                if not dry_run:
                    with db_transaction.atomic():
                        # Relink stock to the asset-leg virtual tx (or None if not found)
                        stock.transaction = asset_leg
                        stock.save(update_fields=["transaction"])
                        if asset_leg:
                            stock_relinked += 1
                        # Delete the now-orphaned primary USD tx
                        tx.delete()
                    deleted += 1

        self.stdout.write(f"\nSummary: {deleted} primary txs deleted, {made_virtual} made virtual, {stock_relinked} stocks relinked\n")
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes saved ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
