import logging

from celery import shared_task
from django.core.management import call_command


logger = logging.getLogger(__name__)


@shared_task
def fetch_emails_task():
    logger.info("Starting fetch_emails task")
    call_command('fetch_emails')
    logger.info("Finished fetch_emails task")