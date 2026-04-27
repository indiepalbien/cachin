"""Debug duplicate and categorization issues."""
import datetime
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Debug duplicate transactions and categorization"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=7)
        parser.add_argument("--date", type=str, default=None,
                            help="Show txs/emails for a specific date (YYYY-MM-DD)")

    def handle(self, *args, **options):
        from expenses.models import PendingTransaction, Transaction, UserEmailMessage
        user_id = options["user_id"]

        # Date-specific view
        if options["date"]:
            target = datetime.date.fromisoformat(options["date"])
            self._show_date(user_id, target)
            return

        self._show_full(user_id)

    def _show_date(self, user_id, target):
        from expenses.models import Transaction, UserEmailMessage

        txs = Transaction.objects.filter(
            user_id=user_id, date=target
        ).order_by("id").select_related("source", "category")
        self.stdout.write(f"\n=== TXS ON {target}: {txs.count()} ===\n")
        for t in txs:
            src = t.source.name if t.source else "—"
            cat = t.category.name if t.category else "—"
            virt = "V" if t.is_virtual else "R"
            self.stdout.write(
                f"  [{virt}] id={t.id:5d} {t.amount:>10.2f} {t.currency:<5s} "
                f"src={src:<15s} cat={cat:<15s} "
                f"ext_id={t.external_id[:35] if t.external_id else 'None':<35s} "
                f"'{t.description[:45]}'\n"
            )

        emails = UserEmailMessage.objects.filter(
            user_id=user_id, date__date=target
        ).order_by("id")
        self.stdout.write(f"\n=== EMAILS ON {target}: {emails.count()} ===\n")
        for e in emails:
            err = f" ERR={e.processing_error[:40]}" if e.processing_error else ""
            self.stdout.write(
                f"  id={e.id} from='{(e.from_address or '')[:40]}' "
                f"subj='{(e.subject or '')[:55]}'{err}\n"
            )

    def _show_full(self, user_id):
        from expenses.models import PendingTransaction, Transaction, UserEmailMessage, Category

        # Pending transactions (duplicates)
        pts = PendingTransaction.objects.filter(user_id=user_id).order_by("-id")
        self.stdout.write(f"\n=== PENDING TRANSACTIONS: {pts.count()} total ===\n")
        for p in pts[:30]:
            desc = ""
            if p.payload:
                desc = p.payload.get("description", p.payload.get("symbol", ""))[:50]
            self.stdout.write(
                f"  id={p.id} reason={p.reason} ext_id={p.external_id[:50]}... "
                f"desc='{desc}'\n"
            )

        # IBKR transactions without category
        ibkr_txs = Transaction.objects.filter(
            user_id=user_id,
            source__name__startswith="ibkr:",
            is_virtual=True,
            category__isnull=True,
        ).select_related("source", "category")
        self.stdout.write(f"\n=== IBKR VIRTUAL TXS WITHOUT CATEGORY: {ibkr_txs.count()} ===\n")

        # IBKR transactions WITH category
        ibkr_cat = Transaction.objects.filter(
            user_id=user_id,
            source__name__startswith="ibkr:",
            is_virtual=True,
            category__isnull=False,
        ).select_related("category")
        self.stdout.write(f"=== IBKR VIRTUAL TXS WITH CATEGORY: {ibkr_cat.count()} ===\n")
        for t in ibkr_cat[:5]:
            self.stdout.write(f"  tx={t.id} cat='{t.category}'\n")

        # Check for "investment" category
        from expenses.models import Category
        cats = Category.objects.filter(user_id=user_id, name__icontains="invest")
        self.stdout.write(f"\n=== INVESTMENT-LIKE CATEGORIES ===\n")
        for c in cats:
            self.stdout.write(f"  id={c.id} name='{c.name}'\n")

        # Uber-related transactions
        uber_txs = Transaction.objects.filter(
            user_id=user_id,
            description__icontains="uber",
        ).order_by("-date")[:20]
        self.stdout.write(f"\n=== RECENT UBER TRANSACTIONS: {uber_txs.count()} shown ===\n")
        for t in uber_txs:
            self.stdout.write(
                f"  id={t.id} {t.date} {t.amount:>8.2f} {t.currency} "
                f"status={t.status} cat={t.category_id} "
                f"ext_id={t.external_id[:40] if t.external_id else 'None'}... "
                f"'{t.description[:40]}'\n"
            )

        # Uber pending
        uber_pending = PendingTransaction.objects.filter(
            user_id=user_id,
        )
        uber_count = 0
        for p in uber_pending:
            if p.payload and "uber" in str(p.payload).lower():
                uber_count += 1
        self.stdout.write(f"\n=== UBER PENDING: {uber_count} ===\n")

        # Recent unrecognized emails
        unrecognized = UserEmailMessage.objects.filter(
            user_id=user_id,
            processing_error__icontains="Unrecognized sender",
        ).order_by("-date")[:10]
        self.stdout.write(f"\n=== RECENT UNRECOGNIZED EMAILS: {unrecognized.count()} shown ===\n")
        for m in unrecognized:
            self.stdout.write(
                f"  id={m.id} {m.date} from='{m.from_address[:40]}' "
                f"subject='{(m.subject or '')[:50]}'\n"
            )
