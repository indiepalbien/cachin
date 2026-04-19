"""Show all ibkr:USD transactions to verify deposit/withdrawal coverage."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show all ibkr:USD transactions for a user"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=7)

    def handle(self, *args, **options):
        from expenses.models import Transaction
        user_id = options["user_id"]

        txs = (
            Transaction.objects
            .filter(user_id=user_id, source__name="ibkr:USD")
            .order_by("date", "id")
            .select_related("source")
        )

        self.stdout.write(f"ibkr:USD transactions for user={user_id}: {txs.count()} total\n\n")
        running = 0
        for tx in txs:
            running += tx.amount
            virtual = "V" if tx.is_virtual else "R"
            self.stdout.write(
                f"  [{virtual}] id={tx.id:5d} {tx.date} {tx.amount:>12.2f} USD  "
                f"running={running:>12.2f}  paired={tx.paired_transaction_id}  "
                f"'{tx.description[:55]}'\n"
            )
        self.stdout.write(f"\nFinal ibkr:USD balance: {running:.2f}\n")
