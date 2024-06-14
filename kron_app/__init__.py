import os
import sys
from datetime import timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bootstrap import Bootstrap
from celery import Celery
from kron_app.config import mkconfig

# https://flask.palletsprojects.com/en/2.0.x/patterns/celery/
def make_celery(app):
    celery = Celery(
        app.import_name,
        broker=app.config['CELERY_BROKER_URL'],
        # `z3-solver` gets upset if `stdout` is replaced with a
        # logger, hence:
        worker_redirect_stdouts=False
    )

    # https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html#beat-entries
    celery.conf.beat_schedule = {
        'gcal_renew': {
            'task': 'kron_app.tasks.task_gcal_renew',
            'schedule': timedelta(seconds=30),
            'args': []
        },
        'timed_state_changes': {
            'task': 'kron_app.tasks.task_timed_state_changes',
            'schedule': timedelta(minutes=1),
            'args': []
        },
        'gcal_update_api_quotas': {
            'task': 'kron_app.tasks.task_gcal_update_api_quotas',
            'schedule': timedelta(minutes=15),
            'args': []
        },
        'purge_task_table': {
            'task': 'kron_app.tasks.task_purge_task_table',
            'schedule': timedelta(days=1),
            'args': []
        },
    }

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

if os.path.basename(sys.argv[0]) == 'pytest':
    os.environ['FLASK_ENV'] = 'test'
elif not 'FLASK_ENV' in os.environ:
    os.environ['FLASK_ENV'] = 'development'
app = Flask(__name__)
app.config.update(**mkconfig(app.config['ENV']))

db = SQLAlchemy(app)
migrate = Migrate(app, db)
bootstrap = Bootstrap(app)
celery = make_celery(app)

login_manager = LoginManager(app)
login_manager.login_view = 'sign_in'
login_manager.login_message = 'Please sign in to access this page.'
login_manager.session_protection = 'strong'

from kron_app import routes, errors
import kron_app.templates.helpers
import kron_app.utils
