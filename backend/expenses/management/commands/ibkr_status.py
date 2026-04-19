"""Show IBKR email and stock status, and optionally reprocess old emails."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show IBKR email/stock status and optionally reprocess old emails"

    def add_arguments(self, parser):
        parser.add_argument("--reprocess", action="store_true",
                            help="Re-process already-processed IBKR emails")
        parser.add_argument("--user-id", type=int, default=None)

    def handle(self, *args, **options):
        from expenses.models import UserEmailMessage, Stock, Transaction
        from expenses.email_ingest import _process_ibkr_trade

        user_id = options["user_id"]
        reprocess = options["reprocess"]

        ibkr_qs = UserEmailMessage.objects.filter(
            from_address__icontains="interactivebrokers"
        ).order_by("date")
        if user_id:
            ibkr_qs = ibkr_qs.filter(user_id=user_id)

        self.stdout.write(f"IBKR emails: {ibkr_qs.count()} total\n")
        self.stdout.write(f"  processed:   {ibkr_qs.filter(processed_at__isnull=False).count()}\n")
        self.stdout.write(f"  unprocessed: {ibkr_qs.filter(processed_at__isnull=True).count()}\n\n")

        for msg in ibkr_qs:
            status = "OK" if msg.processed_at else "PENDING"
            err = f" ERR={msg.processing_error[:60]}" if msg.processing_error else ""
            self.stdout.write(
                f"  [{status}] id={msg.id} date={msg.date} user={msg.user_id} "
                f"subject='{(msg.subject or '')[:60]}'{err}\n"
            )

        self.stdout.write("\n")
        stocks = Stock.objects.all().order_by("date")
        if user_id:
            stocks = stocks.filter(user_id=user_id)
        self.stdout.write(f"Stocks: {stocks.count()} total\n")
        for s in stocks:
            action = "BUY" if s.bought else "SELL"
            self.stdout.write(
                f"  {s.date} {action} {s.amount} {s.symbol} @ {s.unitprice} "
                f"tx_id={s.transaction_id} user={s.user_id}\n"
            )

        if reprocess:
            self.stdout.write("\n--- REPROCESSING (errors only) ---\n")
            errored = ibkr_qs.filter(processing_error__isnull=False).exclude(processing_error="")
            self.stdout.write(f"Found {errored.count()} emails with errors to reprocess\n")
            for msg in errored:
                self.stdout.write(f"  Reprocessing msg id={msg.id} subject='{(msg.subject or '')[:60]}'\n")
                msg.processed_at = None
                msg.processing_error = ""
                msg.save(update_fields=["processed_at", "processing_error"])
                result = _process_ibkr_trade(msg)
                if msg.processing_error:
                    self.stdout.write(self.style.ERROR(f"    → STILL FAILED: {msg.processing_error[:80]}\n"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"    → OK result={result}\n"))

        self.stdout.write(self.style.SUCCESS("Done.\n"))
