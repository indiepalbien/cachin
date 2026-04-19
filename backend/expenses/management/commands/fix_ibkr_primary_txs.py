"""
Fix existing IBKR transactions to match the new virtual-tx schema.

New schema:
- Security trades: virtual asset leg (ibkr:SYMBOL) + virtual cash leg (ibkr:SETTLE_CURRENCY)
- Forex trades: two virtual legs (ibkr:USD + ibkr:BASE_CURRENCY)

This command handles two cases:

Case A — stock.transaction is a non-virtual USD tx (old backfill style):
  - Create a virtual asset-leg tx (ibkr:SYMBOL) if one doesn't exist
  - Create a cash-leg tx (ibkr:SETTLE_CURRENCY) if mapping exists
  - Delete the non-virtual USD tx
  - Relink Stock to the new asset-leg virtual tx

Case B — stock.transaction is already a virtual asset-leg tx (already fixed):
  - Skip it (idempotent)

Forex trades where stock.transaction is non-virtual: mark it virtual.

Run with --dry-run first.
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from expenses.models import IBKRSymbolCurrency, Source, Stock, Transaction
from expenses.email_ingest import _is_forex, _convert_usd_to_currency


def _get_or_create_source(user, source_name):
    obj, _ = Source.objects.get_or_create(user=user, name=source_name)
    return obj


class Command(BaseCommand):
    help = "Fix existing IBKR primary transactions to match new virtual-tx schema"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--since", default="2020-01-01")
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
        asset_legs_created = 0
        cash_legs_created = 0
        skipped = 0

        for stock in stocks_qs:
            tx = stock.transaction
            if tx is None:
                self.stdout.write(f"  SKIP Stock id={stock.id}: no transaction linked\n")
                skipped += 1
                continue

            forex = _is_forex(stock.symbol)

            if forex:
                if tx.is_virtual:
                    self.stdout.write(f"  FOREX already virtual: tx id={tx.id}\n")
                    skipped += 1
                else:
                    self.stdout.write(
                        f"  FOREX mark virtual: tx id={tx.id} '{tx.description[:60]}'\n"
                    )
                    if not dry_run:
                        tx.is_virtual = True
                        tx.save(update_fields=["is_virtual"])
                    made_virtual += 1
                continue

            # Security trade
            if tx.is_virtual:
                # Already fixed (stock.transaction is the asset-leg virtual tx)
                self.stdout.write(
                    f"  SECURITY already fixed: Stock id={stock.id} → virtual tx id={tx.id} "
                    f"'{tx.description[:50]}'\n"
                )
                skipped += 1
                continue

            # Non-virtual USD primary tx — needs to be replaced
            symbol_key = stock.symbol.split()[0]
            user = tx.user

            # Find or plan to create the virtual asset-leg tx
            existing_asset = tx.pair.filter(is_virtual=True, currency=symbol_key).first()

            self.stdout.write(
                f"  SECURITY fix: tx id={tx.id} '{tx.description[:55]}' "
                f"(amount={tx.amount} {tx.currency})\n"
            )

            if existing_asset:
                asset_leg = existing_asset
                self.stdout.write(f"    existing asset leg: tx id={asset_leg.id}\n")
            else:
                # Need to create the asset-leg virtual tx
                asset_amount = -stock.amount if stock.bought else stock.amount
                self.stdout.write(
                    f"    create asset leg: ibkr:{symbol_key} amount={asset_amount}\n"
                )
                if not dry_run:
                    asset_leg = Transaction.objects.create(
                        user=user,
                        date=tx.date,
                        description=tx.description,
                        amount=asset_amount,
                        currency=symbol_key,
                        source=_get_or_create_source(user, f"ibkr:{symbol_key}"),
                        external_id=(tx.external_id + ":asset") if tx.external_id else None,
                        status="confirmed",
                        is_virtual=True,
                        paired_transaction=tx,
                    )
                    asset_legs_created += 1
                else:
                    asset_leg = None  # placeholder for dry-run

            # Cash leg in settlement currency
            settlement = IBKRSymbolCurrency.objects.filter(
                user=user, symbol=symbol_key
            ).first()

            if settlement and (asset_leg or dry_run):
                settle_currency = settlement.currency
                existing_cash = (
                    asset_leg.pair.filter(currency=settle_currency, is_virtual=True).exists()
                    if asset_leg else False
                )
                if existing_cash:
                    self.stdout.write(
                        f"    cash leg ibkr:{settle_currency} already exists\n"
                    )
                else:
                    cash_usd = tx.amount  # positive = debit (BUY), negative = credit (SELL)
                    settle_amount = _convert_usd_to_currency(
                        cash_usd, settle_currency, tx.date, user
                    )
                    if settle_amount is not None:
                        self.stdout.write(
                            f"    create cash leg ibkr:{settle_currency} amount={settle_amount}\n"
                        )
                        if not dry_run and asset_leg:
                            Transaction.objects.create(
                                user=user,
                                date=tx.date,
                                description=tx.description,
                                amount=settle_amount,
                                currency=settle_currency,
                                source=_get_or_create_source(user, f"ibkr:{settle_currency}"),
                                external_id=(asset_leg.external_id.replace(":asset", ":cash")) if asset_leg.external_id else None,
                                status="confirmed",
                                is_virtual=True,
                                paired_transaction=asset_leg,
                            )
                            cash_legs_created += 1
                    else:
                        self.stdout.write(
                            f"    no exchange rate for USD→{settle_currency} on {tx.date}, "
                            f"cash leg skipped\n"
                        )

            # Relink stock and delete the primary USD tx
            if not dry_run:
                with db_transaction.atomic():
                    stock.transaction = asset_leg
                    stock.save(update_fields=["transaction"])
                    if asset_leg:
                        stock_relinked += 1
                    tx.delete()
                deleted += 1

        self.stdout.write(
            f"\nSummary: {deleted} primary txs deleted, {made_virtual} made virtual, "
            f"{stock_relinked} stocks relinked, "
            f"{asset_legs_created} asset legs created, "
            f"{cash_legs_created} cash legs created, "
            f"{skipped} skipped\n"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY RUN — no changes saved ***\n"))
        else:
            self.stdout.write(self.style.SUCCESS("Done.\n"))
