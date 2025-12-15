import logging

from celery import shared_task
from django.core.management import call_command

from expenses.email_ingest import process_new_messages


logger = logging.getLogger(__name__)


@shared_task
def fetch_emails_task():
    logger.info("Starting fetch_emails task")
    call_command('fetch_emails')
    processed = process_new_messages()
    logger.info("Finished fetch_emails task; processed %s messages", processed)