web: gunicorn --bind :8000 kron_app:app
celery_worker: celery -A kron_app.tasks worker -c 1 --loglevel=INFO -B --max-memory-per-child 153600
