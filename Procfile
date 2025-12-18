web: cd backend && python manage.py migrate && python manage.py collectstatic --noinput && gunicorn --worker-tmp-dir /dev/shm misfinanzas.wsgi:application
worker: cd backend && celery -A misfinanzas worker --schedule /tmp/celerybeat-schedule --loglevel=info -E --concurrency 1
beat: cd backend && celery -A misfinanzas beat -l info --schedule /tmp/celerybeat-schedule
