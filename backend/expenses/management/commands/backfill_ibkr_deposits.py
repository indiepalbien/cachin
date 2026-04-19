"""
Backfill IBKR deposits and withdrawals as virtual ibkr:USD transactions.

For each known deposit/withdrawal:
1. Look for an existing bank-side tx (Chase BILL PAYMENT / DIRECT DEPOSIT) matching
   the date and amount that doesn't already have an ibkr:USD counterpart.
2. If found, create the ibkr:USD counterpart and pair it.
3. If not found, create a standalone virtual ibkr:USD tx.

Sign convention (same as rest of system):
  Deposit   (money INTO ibkr)  → ibkr:USD amount = NEGATIVE  (money received)
  Withdrawal (money OUT of ibkr) → ibkr:USD amount = POSITIVE (money spent)
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand

from expenses.models import Source, Transaction

# From IBKR activity statement — (date, ibkr_amount, description)
# ibkr_amount: negative = deposit into IBKR, positive = withdrawal from IBKR
KNOWN_FLOWS = [
    (datetime.date(2026, 2, 4),  Decimal("3000.00"),   "IBKR Disbursement by Diego Kiedanski"),
    (datetime.date(2026, 2, 24), Decimal("-2800.00"),   "IBKR Electronic Fund Transfer deposit"),
    (datetime.date(2026, 3, 9),  Decimal("-5800.00"),   "IBKR Electronic Fund Transfer deposit"),
    (datetime.date(2026, 3, 17), Decimal("-50.00"),     "IBKR Electronic Fund Transfer deposit"),
    (datetime.date(2026, 3, 23), Decimal("-28340.00"),  "IBKR Electronic Fund Transfer deposit"),
    # Apr 8 deposit already exists via BILL PAYMENT counterpart (tx id=1641)
]


def _get_or_create_source(user, source_name):
    obj, _ = Source.objects.get_or_create(user=user, name=source_name)
    return obj


class Command(BaseCommand):
    help = "Backfill known IBKR deposits/withdrawals as virtual ibkr:USD transactions"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--user-id", type=int, default=7)

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        dry_run = options["dry_run"]
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))

        User = get_user_model()
        user = User.objects.get(id=user_id)
        ibkr_usd_source = _get_or_create_source(user, "ibkr:USD")

        created = 0
        paired = 0

        for flow_date, ibkr_amount, description in KNOWN_FLOWS:
            # Check if this flow already exists in ibkr:USD
            # Match by date and amount (with some tolerance for rounding)
            existing = Transaction.objects.filter(
                user=user,
                source=ibkr_usd_source,
                date=flow_date,
                amount=ibkr_amount,
                is_virtual=True,
            ).first()

            if existing:
                self.stdout.write(
                    f"  SKIP {flow_date} {ibkr_amount:>10.2f}: already exists tx id={existing.id}\n"
                )
                continue

            # Look for a matching real bank tx (within ±1 day, matching absolute amount)
            abs_amount = abs(ibkr_amount)
            # For deposits (ibkr_amount < 0): bank tx amount is positive (expense from bank = paying IBKR)
            # For withdrawals (ibkr_amount > 0): bank tx amount is negative (income to bank from IBKR)
            bank_tx_amount = -ibkr_amount  # opposite sign in bank account

            bank_tx = None
            for delta_days in [0, -1, 1]:
                check_date = flow_date + datetime.timedelta(days=delta_days)
                candidates = Transaction.objects.filter(
                    user=user,
                    date=check_date,
                    amount=bank_tx_amount,
                    is_virtual=False,
                ).filter(
                    description__icontains="interactive brokers"
                ).exclude(
                    pair__source=ibkr_usd_source
                )
                if candidates.exists():
                    bank_tx = candidates.first()
                    break

            if bank_tx:
                self.stdout.write(
                    f"  MATCH {flow_date} {ibkr_amount:>10.2f}: bank tx id={bank_tx.id} "
                    f"'{bank_tx.description[:50]}'\n"
                )
            else:
                self.stdout.write(
                    f"  NEW   {flow_date} {ibkr_amount:>10.2f}: no bank tx found, "
                    f"creating standalone virtual\n"
                )

            if not dry_run:
                new_tx = Transaction.objects.create(
                    user=user,
                    date=flow_date,
                    description=description,
                    amount=ibkr_amount,
                    currency="USD",
                    source=ibkr_usd_source,
                    status="confirmed",
                    is_virtual=True,
                    paired_transaction=bank_tx,
                    comments="Backfilled from IBKR activity statement",
                )
                created += 1
                if bank_tx:
                    paired += 1
                self.stdout.write(f"    → created tx id={new_tx.id}\n")

        self.stdout.write(
            f"\nSummary: {created} ibkr:USD txs created ({paired} paired to bank txs)\n"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes saved ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
