"""
Backfill missing settlement cash legs for IBKR virtual asset-leg transactions.

Finds virtual txs on ibkr:SYMBOL sources that have no cash-leg pair,
then creates the cash leg using the IBKRSymbolCurrency mapping.
"""
import re
from decimal import Decimal

from django.core.management.base import BaseCommand

from expenses.models import IBKRSymbolCurrency, Source, Transaction
from expenses.email_ingest import _convert_usd_to_currency, _is_forex

_PRICE_RE = re.compile(r'@\s+\$?([\d,]+\.?\d+)', re.I)
_AMOUNT_RE = re.compile(r'(?:BUY|SELL)\s+([\d,]+\.?\d*)', re.I)


def _get_or_create_source(user, source_name):
    obj, _ = Source.objects.get_or_create(user=user, name=source_name)
    return obj


class Command(BaseCommand):
    help = "Backfill missing settlement cash legs for IBKR virtual asset txs"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--user-id", type=int, default=None)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        user_id = options["user_id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN ***\n"))

        # Find all virtual txs on ibkr:SYMBOL sources (not ibkr:USD/EUR/etc — those are cash legs)
        qs = Transaction.objects.filter(
            is_virtual=True,
        ).select_related("user", "source")

        if user_id:
            qs = qs.filter(user_id=user_id)

        created = 0
        skipped = 0

        for tx in qs:
            if not tx.source or not tx.source.name.startswith("ibkr:"):
                continue
            symbol_key = tx.source.name[len("ibkr:"):]

            # Skip forex currencies and standard currencies (3-char ISO)
            if len(symbol_key) <= 3 or _is_forex(symbol_key):
                continue

            # This is a virtual asset-leg tx (ibkr:SUSW, ibkr:VWRA, etc)
            # Check if it already has a cash leg
            has_cash = tx.pair.filter(is_virtual=True).exclude(
                source__name=f"ibkr:{symbol_key}"
            ).exists()

            if has_cash:
                self.stdout.write(
                    f"  SKIP tx id={tx.id} '{tx.description[:50]}': cash leg exists\n"
                )
                skipped += 1
                continue

            settlement = IBKRSymbolCurrency.objects.filter(
                user=tx.user, symbol=symbol_key
            ).first()

            if not settlement:
                self.stdout.write(
                    f"  SKIP tx id={tx.id} '{tx.description[:50]}': no mapping for {symbol_key}\n"
                )
                skipped += 1
                continue

            # Extract USD total from description or calculate from amount * unit price
            price_m = _PRICE_RE.search(tx.description)
            amount_m = _AMOUNT_RE.search(tx.description)

            if price_m and amount_m:
                price = Decimal(price_m.group(1).replace(",", ""))
                qty = Decimal(amount_m.group(1).replace(",", ""))
                total_usd = qty * price
            else:
                self.stdout.write(
                    f"  SKIP tx id={tx.id} '{tx.description[:50]}': can't parse price\n"
                )
                skipped += 1
                continue

            # Determine sign: BUY = debit (positive cash out), SELL = credit (negative)
            is_buy = tx.description.upper().startswith("BUY")
            cash_usd = total_usd if is_buy else -total_usd

            settle_amount = _convert_usd_to_currency(
                cash_usd, settlement.currency, tx.date, tx.user
            )

            if settle_amount is None:
                self.stdout.write(
                    f"  SKIP tx id={tx.id} '{tx.description[:50]}': "
                    f"no exchange rate for USD→{settlement.currency} on {tx.date}\n"
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  CREATE cash leg ibkr:{settlement.currency} amount={settle_amount} "
                f"for tx id={tx.id} '{tx.description[:50]}' (user={tx.user_id})\n"
            )

            if not dry_run:
                Transaction.objects.create(
                    user=tx.user,
                    date=tx.date,
                    description=tx.description,
                    amount=settle_amount,
                    currency=settlement.currency,
                    source=_get_or_create_source(tx.user, f"ibkr:{settlement.currency}"),
                    external_id=(tx.external_id.replace(":asset", ":cash") if tx.external_id and ":asset" in tx.external_id
                                 else (tx.external_id + ":cash" if tx.external_id else None)),
                    status="confirmed",
                    is_virtual=True,
                    paired_transaction=tx,
                )
                created += 1

        self.stdout.write(f"\nSummary: {created} cash legs created, {skipped} skipped\n")
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes saved ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
