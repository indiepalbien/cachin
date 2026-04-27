"""Re-categorize specific transactions."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Re-categorize a transaction by ID"

    def add_arguments(self, parser):
        parser.add_argument("tx_id", type=int)
        parser.add_argument("category_name", type=str)
        parser.add_argument("--user-id", type=int, default=7)

    def handle(self, *args, **options):
        from expenses.models import Category, Transaction

        tx = Transaction.objects.get(id=options["tx_id"], user_id=options["user_id"])
        cat = Category.objects.get(user_id=options["user_id"], name__iexact=options["category_name"])
        old = tx.category.name if tx.category else "None"
        tx.category = cat
        tx.save(update_fields=["category"])
        self.stdout.write(
            f"tx id={tx.id} '{tx.description[:50]}': {old} → {cat.name}\n"
        )
