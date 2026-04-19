"""Seed default IBKR symbol→currency mappings for all users."""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from expenses.models import IBKRSymbolCurrency

DEFAULTS = [
    ("SUSW", "EUR"),
    ("VWRA", "USD"),
]


class Command(BaseCommand):
    help = "Seed SUSW→EUR and VWRA→USD IBKRSymbolCurrency mappings"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None)

    def handle(self, *args, **options):
        User = get_user_model()
        user_id = options["user_id"]
        users = User.objects.filter(id=user_id) if user_id else User.objects.all()

        for user in users:
            for symbol, currency in DEFAULTS:
                obj, created = IBKRSymbolCurrency.objects.get_or_create(
                    user=user, symbol=symbol, defaults={"currency": currency}
                )
                status = "created" if created else "already exists"
                self.stdout.write(f"  user={user.id} {symbol}→{currency}: {status}\n")

        self.stdout.write(self.style.SUCCESS("Done.\n"))
