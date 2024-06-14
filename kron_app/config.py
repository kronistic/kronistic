import os
from datetime import timedelta

def get_database_uri(env='development') -> str:
  if env == 'development' or env == 'test':
    dbname = 'kron' if env == 'development' else 'kron_test'
    username = os.environ.get('POSTGRES_USERNAME') or ''
    password = os.environ.get('POSTGRES_PASSWORD') or ''
    host = 'localhost'
    port = 5432
  elif env == 'production':
    dbname = os.environ['RDS_DB_NAME']
    username = os.environ['RDS_USERNAME']
    password = os.environ['RDS_PASSWORD']
    host = os.environ['RDS_HOSTNAME']
    port = os.environ['RDS_PORT']
  else:
    raise Exception('Unknown environment.')

  return f'postgresql://{username}:{password}@{host}:{port}/{dbname}'

def get_hostname(env):
  if env == 'development' or env == 'test':
    return 'localhost:8080'
  else:
    return os.environ['KRON_HOSTNAME']

def mkconfig(env):
  dburi = get_database_uri(env)
  hostname = get_hostname(env)
  return dict(
    # DEBUG: bool = True,
    # TESTING: bool = False,
    # TEMPLATES_AUTO_RELOAD = True,,
    SECRET_KEY = os.environ.get('KRON_SECRET_KEY') or 'secret_tunnel',
    SQLALCHEMY_DATABASE_URI = dburi,
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    # SQLALCHEMY_ECHO = True,
    CELERY_BROKER_URL = f'sqla+{dburi}',
    HOSTNAME = hostname,
    GCAL_WEBHOOK_HOST = os.environ.get('GCAL_WEBHOOK_HOST') or hostname,
    SMTP_LOGIN = os.environ.get('SMTP_LOGIN') or '',
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD') or '',
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY'),
    PERMANENT_SESSION_LIFETIME = timedelta(days=7),
  )
