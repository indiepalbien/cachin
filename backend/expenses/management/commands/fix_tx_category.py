"""Re-categorize specific transactions."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Re-categorize a transaction by ID"

    def add_arguments(self, parser):
        parser.add_argument("tx_id", type=int)
        parser.add_argument("category_name", type=str, nargs="+")
        parser.add_argument("--user-id", type=int, default=7)

    def handle(self, *args, **options):
        from expenses.models import Category, Transaction

        cat_name = " ".join(options["category_name"])
        tx = Transaction.objects.get(id=options["tx_id"], user_id=options["user_id"])
        cat, created = Category.objects.get_or_create(
            user_id=options["user_id"], name=cat_name,
            defaults={"counts_to_total": False},
        )
        if created:
            self.stdout.write(f"Created new category: '{cat_name}' (counts_to_total=False)\n")
        old = tx.category.name if tx.category else "None"
        tx.category = cat
        tx.save(update_fields=["category"])
        self.stdout.write(
            f"tx id={tx.id} '{tx.description[:50]}': {old} → {cat.name}\n"
        )
