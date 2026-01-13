from django.core.management.base import BaseCommand

from expenses.models import UserEmailMessage, PendingTransaction


class Command(BaseCommand):
    help = "Clear stored UserEmailMessage and PendingTransaction entries (useful for reprocessing)."

    def handle(self, *args, **options):
        msg_count = UserEmailMessage.objects.count()
        pending_count = PendingTransaction.objects.count()
        UserEmailMessage.objects.all().delete()
        PendingTransaction.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {msg_count} UserEmailMessage and {pending_count} PendingTransaction entries."))
