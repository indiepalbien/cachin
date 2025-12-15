import email
import imaplib
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone

from expenses.models import UserEmailConfig, UserEmailMessage


class Command(BaseCommand):
    help = "Fetch new emails from IMAP, match aliases to users, and store EML"

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Mailbox username (optional if per-user)')
        parser.add_argument('--password', type=str, help='Mailbox password (optional if per-user)')
        parser.add_argument('--mailbox', type=str, default='INBOX', help='Mailbox folder to scan')

    def handle(self, *args, **options):
        username = options.get('username')
        password = options.get('password')
        mailbox = options.get('mailbox')

        host = settings.EMAIL_FETCH_IMAP_HOST
        port = settings.EMAIL_FETCH_IMAP_PORT
        use_ssl = settings.EMAIL_FETCH_IMAP_SSL

        self.stdout.write(self.style.NOTICE(f"Connecting to IMAP {host}:{port} ssl={use_ssl}"))

        if use_ssl:
            client = imaplib.IMAP4_SSL(host, port)
        else:
            client = imaplib.IMAP4(host, port)

        if username and password:
            client.login(username, password)
        else:
            # If not provided, try to use a shared mailbox from env
            env_user = getattr(settings, 'EMAIL_FETCH_USER', None) or None
            env_pass = getattr(settings, 'EMAIL_FETCH_PASS', None) or None
            if not (env_user and env_pass):
                raise CommandError('Missing mailbox credentials. Provide --username/--password or set EMAIL_FETCH_USER/EMAIL_FETCH_PASS.')
            client.login(env_user, env_pass)

        client.select(mailbox)
        status, data = client.search(None, 'UNSEEN')
        if status != 'OK':
            self.stdout.write(self.style.WARNING('No UNSEEN search results'))
            return

        ids = data[0].split()
        self.stdout.write(self.style.NOTICE(f"Found {len(ids)} unseen messages"))

        # Map of alias address to user id
        alias_map = {cfg.full_address.lower(): cfg.user_id for cfg in UserEmailConfig.objects.filter(active=True)}

        def _decode_header(value: Optional[str]) -> str:
            if not value:
                return ''
            try:
                return str(make_header(decode_header(value)))
            except Exception:
                return value

        for msg_id in ids:
            status, msg_data = client.fetch(msg_id, '(RFC822)')
            if status != 'OK' or not msg_data:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = _decode_header(msg.get('Subject'))
            from_addr = msg.get('From', '')
            tos = msg.get_all('To', []) or []
            cc = msg.get_all('Cc', []) or []
            recipients = ','.join(tos + cc)
            date_header = msg.get('Date')
            parsed_date = None
            if date_header:
                try:
                    parsed_date = parsedate_to_datetime(date_header)
                    if parsed_date and parsed_date.tzinfo is None:
                        parsed_date = timezone.make_aware(parsed_date, timezone=timezone.utc)
                except Exception:
                    parsed_date = None

            # Try to match any recipient to a known alias
            matched_user_id = None
            for rcpt in (tos + cc):
                # Extract email address part
                addr = rcpt
                if '<' in rcpt and '>' in rcpt:
                    addr = rcpt.split('<')[-1].split('>')[0]
                addr = addr.strip().lower()
                if addr in alias_map:
                    matched_user_id = alias_map[addr]
                    break

            if not matched_user_id:
                # Skip if no match
                continue

            # Parse message-id and date
            message_id = (msg.get('Message-Id') or msg.get('Message-ID') or '').strip()

            # Skip if already stored for this user/message_id
            if UserEmailMessage.objects.filter(user_id=matched_user_id, message_id=message_id).exists():
                client.store(msg_id, '+FLAGS', '\\Seen')
                continue

            try:
                UserEmailMessage.objects.create(
                    user_id=matched_user_id,
                    message_id=message_id or str(msg_id, 'utf-8'),
                    subject=subject,
                    from_address=from_addr,
                    to_addresses=recipients,
                    date=parsed_date,
                    raw_eml=raw,
                )
                self.stdout.write(self.style.SUCCESS(f"Stored email for user {matched_user_id}: {subject}"))
                # Mark as seen
                client.store(msg_id, '+FLAGS', '\\Seen')
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skip storing message {msg_id}: {e}"))

        client.logout()
        self.stdout.write(self.style.SUCCESS('Done'))