from django.core.management.base import BaseCommand, CommandError
from expenses.models import UserEmailMessage


class Command(BaseCommand):
    help = "Download a stored EML by id to stdout (or redirect)."

    def add_arguments(self, parser):
        parser.add_argument('id', type=int, help='UserEmailMessage id')

    def handle(self, *args, **options):
        mid = options['id']
        try:
            msg = UserEmailMessage.objects.get(pk=mid)
        except UserEmailMessage.DoesNotExist:
            raise CommandError(f"UserEmailMessage {mid} not found")
        self.stdout.buffer.write(bytes(msg.raw_eml))
