web: cd backend && python manage.py migrate && python manage.py collectstatic --noinput && gunicorn --worker-tmp-dir /dev/shm misfinanzas.wsgi:application
worker: cd backend && celery -A misfinanzas worker -l info
beat: cd backend && celery -A misfinanzas beat -l info
