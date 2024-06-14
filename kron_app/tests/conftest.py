import pytest
from datetime import datetime
from kron_app import db, app
from sqlalchemy_utils import database_exists, create_database, drop_database

@pytest.fixture(scope="session")
def create_test_database():
    url = app.config['SQLALCHEMY_DATABASE_URI']
    if database_exists(url):
        raise Exception(f'database {url} already exists')
    create_database(url)
    yield
    drop_database(url)

@pytest.fixture(scope="function")
def testdb(create_test_database):
    db.create_all()
    yield
    # I'm not entirely sure this is the right thing to do, but without
    # `drop_all` hangs, so we need /something/ like this.
    db.session.close()
    db.drop_all()

@pytest.fixture(scope='function')
def utcnow():
    return datetime.utcnow()
