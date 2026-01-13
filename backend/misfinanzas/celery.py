import os

from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'misfinanzas.settings')

app = Celery('misfinanzas')

# Use Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in installed apps
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    # Simple debug task to verify worker wiring
    print(f'Request: {self.request!r}')