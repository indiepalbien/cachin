from django.core.management.base import BaseCommand

from expenses.email_ingest import process_new_messages


class Command(BaseCommand):
    help = "Process stored UserEmailMessage entries into transactions/pending duplicates."

    def handle(self, *args, **options):
        processed = process_new_messages()
        self.stdout.write(self.style.SUCCESS(f"Processed {processed} messages."))
