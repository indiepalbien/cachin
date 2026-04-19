"""
Backfill all 2025 IBKR activity: trades (VWRA, VWRA.L) and deposits/withdrawals.

Source: IBKR activity statement for 2025.
All trades are USD-settled, so no exchange rate lookups needed.

For each trade:
  - Creates a Stock record
  - Creates a virtual ibkr:SYMBOL asset-leg tx
  - Creates a virtual ibkr:USD cash-leg tx

For each deposit/withdrawal:
  - Creates a virtual ibkr:USD tx (negative = deposit in, positive = withdrawal out)
  - Pairs with existing bank tx if found (description contains 'interactive brokers')
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand

from expenses.models import IBKRSymbolCurrency, Source, Stock, Transaction

# (date, qty_signed, symbol, unitprice, proceeds)
# qty_signed: positive = BUY, negative = SELL
# proceeds: positive = cash in (SELL), negative = cash out (BUY)
TRADES_2025 = [
    # VWRA (USD)
    ("2025-03-24", -426,  "VWRA LSEETF",  Decimal("141.0000"),      Decimal("60066.00")),
    ("2025-05-23",   13,  "VWRA LSEETF",  Decimal("143.557346154"), Decimal("-1866.25")),
    ("2025-06-13",    4,  "VWRA LSEETF",  Decimal("148.2160"),      Decimal("-592.86")),
    ("2025-07-14",    4,  "VWRA LSEETF",  Decimal("153.1246"),      Decimal("-612.50")),
    ("2025-07-23",   32,  "VWRA LSEETF",  Decimal("155.7969"),      Decimal("-4985.50")),
    ("2025-07-28",   45,  "VWRA LSEETF",  Decimal("156.3529"),      Decimal("-7035.88")),
    ("2025-08-11",   37,  "VWRA LSEETF",  Decimal("156.9490"),      Decimal("-5807.11")),
    ("2025-08-26",   36,  "VWRA LSEETF",  Decimal("158.3643"),      Decimal("-5701.11")),
    ("2025-09-10",   36,  "VWRA LSEETF",  Decimal("161.1600"),      Decimal("-5801.76")),
    ("2025-09-24",    1,  "VWRA LSEETF",  Decimal("163.8600"),      Decimal("-163.86")),
    ("2025-09-25",   35,  "VWRA LSEETF",  Decimal("162.1400"),      Decimal("-5674.90")),
    ("2025-10-10",   35,  "VWRA LSEETF",  Decimal("165.5800"),      Decimal("-5795.30")),
    ("2025-10-24",   35,  "VWRA LSEETF",  Decimal("167.2234"),      Decimal("-5852.82")),
    ("2025-11-11",   34,  "VWRA LSEETF",  Decimal("167.8200"),      Decimal("-5705.88")),
    # VWRA.L (USD)
    ("2025-11-26",   54,  "VWRA.L LSEETF", Decimal("166.5009"),     Decimal("-8991.05")),
    ("2025-12-10",   34,  "VWRA.L LSEETF", Decimal("168.4200"),     Decimal("-5726.28")),
]

# (date, ibkr_usd_amount, description)
# ibkr_usd_amount: negative = deposit into IBKR, positive = withdrawal from IBKR
DEPOSITS_2025 = [
    ("2025-03-24", Decimal("60200.00"),   "IBKR Disbursement by Diego Kiedanski"),
    ("2025-05-23", Decimal("-2000.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-06-13", Decimal("-600.00"),    "IBKR Electronic Fund Transfer deposit"),
    ("2025-07-11", Decimal("-600.00"),    "IBKR Electronic Fund Transfer deposit"),
    ("2025-07-23", Decimal("-5000.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-07-28", Decimal("-7000.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-08-08", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-08-25", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-09-10", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-09-25", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-10-10", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-10-24", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-11-10", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-11-25", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-11-25", Decimal("-3050.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-12-10", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    ("2025-12-24", Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
]


def _get_or_create_source(user, source_name):
    obj, _ = Source.objects.get_or_create(user=user, name=source_name)
    return obj


class Command(BaseCommand):
    help = "Backfill 2025 IBKR trades and deposits/withdrawals"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--user-id", type=int, default=7)

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from django.db import transaction as db_transaction

        dry_run = options["dry_run"]
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))

        User = get_user_model()
        user = User.objects.get(id=user_id)

        # Ensure VWRA.L → USD mapping exists
        obj, created = IBKRSymbolCurrency.objects.get_or_create(
            user=user, symbol="VWRA.L", defaults={"currency": "USD"}
        )
        if created:
            self.stdout.write("  Created IBKRSymbolCurrency: VWRA.L → USD\n")

        trades_created = 0
        trades_skipped = 0
        deposits_created = 0
        deposits_skipped = 0

        # --- TRADES ---
        self.stdout.write("\n=== TRADES ===\n")
        for row in TRADES_2025:
            trade_date = datetime.date.fromisoformat(row[0])
            qty_signed = row[1]
            symbol = row[2]
            unitprice = row[3]
            proceeds = row[4]

            symbol_key = symbol.split()[0]
            is_buy = qty_signed > 0
            qty = abs(qty_signed)
            action = "BUY" if is_buy else "SELL"
            description = f"{action} {qty} {symbol} @ ${unitprice}"

            # Cash leg: negate proceeds (proceeds negative=buy, positive=sell → ibkr:USD positive=out, negative=in)
            cash_usd = -proceeds  # e.g. proceeds=-1866 → cash_usd=+1866 (USD going out to buy)

            # Check if Stock already exists (by date + symbol + qty)
            existing_stock = Stock.objects.filter(
                user=user,
                date=trade_date,
                symbol=symbol,
                amount=qty,
                bought=is_buy,
            ).first()

            if existing_stock:
                self.stdout.write(
                    f"  SKIP {description} on {trade_date}: Stock id={existing_stock.id} exists\n"
                )
                trades_skipped += 1
                continue

            self.stdout.write(
                f"  CREATE {description} on {trade_date} "
                f"| ibkr:{symbol_key} {'−' if is_buy else '+'}{qty} "
                f"| ibkr:USD {cash_usd:+.2f}\n"
            )

            if not dry_run:
                with db_transaction.atomic():
                    # Asset-leg virtual tx
                    asset_amount = -qty if is_buy else qty
                    asset_tx = Transaction.objects.create(
                        user=user,
                        date=trade_date,
                        description=description,
                        amount=Decimal(str(asset_amount)),
                        currency=symbol_key,
                        source=_get_or_create_source(user, f"ibkr:{symbol_key}"),
                        status="confirmed",
                        is_virtual=True,
                        comments="Backfilled from 2025 IBKR activity statement",
                    )

                    # Cash-leg virtual tx (USD)
                    Transaction.objects.create(
                        user=user,
                        date=trade_date,
                        description=description,
                        amount=cash_usd,
                        currency="USD",
                        source=_get_or_create_source(user, "ibkr:USD"),
                        status="confirmed",
                        is_virtual=True,
                        paired_transaction=asset_tx,
                        comments="Backfilled from 2025 IBKR activity statement",
                    )

                    # Stock record
                    Stock.objects.create(
                        user=user,
                        date=trade_date,
                        symbol=symbol,
                        bought=is_buy,
                        amount=qty,
                        unitprice=unitprice,
                        transaction=asset_tx,
                    )
                trades_created += 1

        # --- DEPOSITS / WITHDRAWALS ---
        self.stdout.write("\n=== DEPOSITS & WITHDRAWALS ===\n")
        ibkr_usd_source = _get_or_create_source(user, "ibkr:USD")

        for row in DEPOSITS_2025:
            dep_date = datetime.date.fromisoformat(row[0])
            ibkr_amount = row[1]
            description = row[2]

            # Check if already exists
            existing = Transaction.objects.filter(
                user=user,
                source=ibkr_usd_source,
                date=dep_date,
                amount=ibkr_amount,
                is_virtual=True,
                comments__icontains="activity statement",
            ).first()

            if existing:
                self.stdout.write(
                    f"  SKIP {dep_date} {ibkr_amount:>12.2f}: already exists tx id={existing.id}\n"
                )
                deposits_skipped += 1
                continue

            # Try to pair with a real bank tx
            bank_tx_amount = -ibkr_amount
            bank_tx = None
            for delta in [0, -1, 1]:
                check_date = dep_date + datetime.timedelta(days=delta)
                candidates = Transaction.objects.filter(
                    user=user,
                    date=check_date,
                    amount=bank_tx_amount,
                    is_virtual=False,
                ).filter(description__icontains="interactive brokers").exclude(
                    pair__source=ibkr_usd_source
                )
                if candidates.exists():
                    bank_tx = candidates.first()
                    break

            if bank_tx:
                self.stdout.write(
                    f"  MATCH {dep_date} {ibkr_amount:>12.2f}: bank tx id={bank_tx.id} "
                    f"'{bank_tx.description[:50]}'\n"
                )
            else:
                self.stdout.write(
                    f"  NEW   {dep_date} {ibkr_amount:>12.2f}: standalone virtual\n"
                )

            if not dry_run:
                Transaction.objects.create(
                    user=user,
                    date=dep_date,
                    description=description,
                    amount=ibkr_amount,
                    currency="USD",
                    source=ibkr_usd_source,
                    status="confirmed",
                    is_virtual=True,
                    paired_transaction=bank_tx,
                    comments="Backfilled from 2025 IBKR activity statement",
                )
                deposits_created += 1

        self.stdout.write(
            f"\nSummary: {trades_created} trades created ({trades_skipped} skipped), "
            f"{deposits_created} deposit/withdrawal txs created ({deposits_skipped} skipped)\n"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes saved ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
