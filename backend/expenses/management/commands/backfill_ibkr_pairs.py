"""
Management command to backfill paired virtual transactions for existing IBKR trades.

For each existing Stock record that has a linked Transaction (the USD leg):
- Creates a virtual paired transaction on ibkr:SUSW / ibkr:EUR etc.
- Updates the primary transaction's source from "ibkr" -> "ibkr:USD"
- Skips if a pair already exists

For bank transactions (non-virtual, non-IBKR-trade) with "INTERACTIVE BROKERS"
in the description that don't already have a pair:
- Creates a virtual ibkr:USD credit leg

Run with --dry-run first to preview changes.
"""
import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from expenses.models import Source, Stock, Transaction
from expenses.email_ingest import (
    _get_or_create_source,
    _is_forex,
    _symbol_key,
    _IBKR_DEPOSIT_MARKER,
)

import logging
logger = logging.getLogger(__name__)

_FOREX_PATTERN = re.compile(r'^[A-Z]{3}\.[A-Z]{3}$')


class Command(BaseCommand):
    help = "Backfill paired virtual transactions for existing IBKR trades (April 2026 and forward)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database",
        )
        parser.add_argument(
            "--since",
            default="2026-04-01",
            help="Only process transactions on or after this date (YYYY-MM-DD). Default: 2026-04-01",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="Limit to a specific user ID (default: all users)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        since = date.fromisoformat(options["since"])
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes will be saved ***\n"))

        self.stdout.write(f"Processing transactions from {since} onward\n")

        # ----------------------------------------------------------------
        # Part 1: IBKR trades (via Stock records)
        # ----------------------------------------------------------------
        stocks_qs = Stock.objects.filter(date__gte=since).select_related("transaction", "transaction__user", "transaction__source")
        if user_id:
            stocks_qs = stocks_qs.filter(user_id=user_id)

        trade_created = 0
        trade_skipped = 0
        source_updated = 0

        for stock in stocks_qs:
            tx = stock.transaction
            if tx is None:
                self.stdout.write(f"  SKIP Stock id={stock.id} — no linked transaction\n")
                trade_skipped += 1
                continue

            # Skip if already has a pair
            if tx.pair.exists():
                self.stdout.write(f"  SKIP Stock id={stock.id} tx id={tx.id} — already paired\n")
                trade_skipped += 1
                continue

            user = tx.user
            action = "BUY" if stock.bought else "SELL"
            forex = _is_forex(stock.symbol)

            if forex:
                base_currency = stock.symbol.split(".")[0]
                paired_amount = -stock.amount if stock.bought else stock.amount
                paired_source_name = f"ibkr:{base_currency}"
                paired_currency = base_currency
            else:
                sym_key = _symbol_key(stock.symbol)
                paired_amount = -stock.amount if stock.bought else stock.amount
                paired_source_name = f"ibkr:{sym_key}"
                paired_currency = sym_key

            self.stdout.write(
                f"  {action} Stock id={stock.id} tx id={tx.id} "
                f"{stock.amount} {stock.symbol} → create virtual tx "
                f"amount={paired_amount} currency={paired_currency} source={paired_source_name}\n"
            )

            if not dry_run:
                with db_transaction.atomic():
                    # Update primary tx source from "ibkr" -> "ibkr:USD" if needed
                    if tx.source and tx.source.name == "ibkr":
                        ibkr_usd_source = _get_or_create_source(user, "ibkr:USD")
                        tx.source = ibkr_usd_source
                        tx.save(update_fields=["source"])
                        source_updated += 1

                    Transaction.objects.create(
                        user=user,
                        date=tx.date,
                        description=tx.description,
                        amount=paired_amount,
                        currency=paired_currency,
                        source=_get_or_create_source(user, paired_source_name),
                        external_id=tx.external_id + ":pair" if tx.external_id else None,
                        status="confirmed",
                        is_virtual=True,
                        paired_transaction=tx,
                    )
            trade_created += 1

        self.stdout.write(f"\nTrades: {trade_created} pairs to create, {trade_skipped} skipped, {source_updated} sources updated to ibkr:USD\n")

        # ----------------------------------------------------------------
        # Part 2: Bank deposit transactions ("INTERACTIVE BROKERS")
        # ----------------------------------------------------------------
        deposits_qs = Transaction.objects.filter(
            date__gte=since,
            is_virtual=False,
            description__icontains=_IBKR_DEPOSIT_MARKER,
        ).exclude(
            pair__isnull=False  # already has a pair
        )
        if user_id:
            deposits_qs = deposits_qs.filter(user_id=user_id)

        deposit_created = 0
        deposit_skipped = 0

        for tx in deposits_qs:
            # Extra guard: skip if it's already an ibkr:* source (it's already the virtual leg)
            if tx.source and tx.source.name.startswith("ibkr:"):
                deposit_skipped += 1
                continue

            self.stdout.write(
                f"  DEPOSIT tx id={tx.id} '{tx.description[:60]}' "
                f"amount={tx.amount} {tx.currency} → create ibkr:USD credit {-tx.amount}\n"
            )

            if not dry_run:
                Transaction.objects.create(
                    user=tx.user,
                    date=tx.date,
                    description=tx.description,
                    amount=-tx.amount,
                    currency=tx.currency,
                    source=_get_or_create_source(tx.user, "ibkr:USD"),
                    status="confirmed",
                    is_virtual=True,
                    paired_transaction=tx,
                    comments=f"Backfill: IBKR deposit counterpart for tx #{tx.pk}",
                )
            deposit_created += 1

        self.stdout.write(f"Deposits: {deposit_created} pairs to create, {deposit_skipped} skipped\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n*** DRY RUN complete — rerun without --dry-run to apply ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nDone. Created {trade_created + deposit_created} virtual transactions.\n"
            ))
