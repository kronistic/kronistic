import pytest
from sqlalchemy.exc import IntegrityError
from kron_app import db
from kron_app.models import User, Email
from kron_app.users import find_user_by_email, find_user_by_primary_email, record_sign_up_step, max_sign_up_step, SignUpStep

def test_create_user(testdb):
    u = User(email='paul@kronistic.com')
    db.session.add(u)
    db.session.commit()
    db.session.rollback()
    assert User.query.count() == 1
    assert Email.query.count() == 1
    u = User.query.first()
    e = Email.query.first()
    assert u.primary_email == e
    assert e.user == u
    assert u.email == 'paul@kronistic.com'
    assert u.primary_email.address == 'paul@kronistic.com'
    assert len(u.emails) == 1

def test_creating_user_without_email(testdb):
    u = User()
    db.session.add(u)
    with pytest.raises(IntegrityError) as excinfo:
        db.session.commit()
    msg = 'null value in column "primary_email_id" of relation "users" violates not-null constraint'
    assert msg in str(excinfo.value)

def test_create_email_without_user(testdb):
    e = Email(address='paul@kronistic.com')
    db.session.add(e)
    db.session.commit()
    db.session.rollback()
    assert Email.query.count() == 1

def test_add_email_alias(testdb):
    u = User(email='paul@kronistic.com')
    db.session.add(u)
    db.session.commit()
    db.session.rollback()
    assert User.query.count() == 1
    u.emails.append(Email(address='paul@example.com'))
    db.session.commit()
    db.session.rollback()
    assert len(u.emails) == 2
    assert set(e.address for e in u.emails) == {'paul@kronistic.com', 'paul@example.com'}
    assert u.aliases == ['paul@example.com']

def test_find_user_by_email(testdb):
    u = User(email='paul@kronistic.com')
    u.emails.append(Email(address='paul@example.com'))
    db.session.add(u)
    db.session.commit()
    db.session.rollback()
    assert User.query.count() == 1
    assert Email.query.count() == 2
    assert find_user_by_email('noah@kronistic.com') is None
    assert find_user_by_email('paul@kronistic.com') == u
    assert find_user_by_email('paul@example.com') == u

def test_find_user_by_primary_email(testdb):
    u = User(email='paul@kronistic.com')
    u.emails.append(Email(address='paul@example.com'))
    db.session.add(u)
    db.session.commit()
    db.session.rollback()
    assert User.query.count() == 1
    assert Email.query.count() == 2
    assert find_user_by_primary_email('paul@kronistic.com') == u
    assert find_user_by_primary_email('paul@example.com') is None

def test_record_sign_up_step(testdb):
    e = Email(address='paul@kronistic.com', uid='uid')
    db.session.add(e)
    db.session.commit()
    assert max_sign_up_step(e) is None
    record_sign_up_step(None, SignUpStep.ACCESS_INVITE_PAGE)
    assert max_sign_up_step(e) is None
    record_sign_up_step(e, SignUpStep.ACCESS_INVITE_PAGE)
    db.session.rollback()
    assert max_sign_up_step(e)[0] == SignUpStep.ACCESS_INVITE_PAGE
    record_sign_up_step(e.uid, SignUpStep.GOOGLE_OAUTH_CALLBACK_ERROR, 'no_access')
    db.session.rollback()
    assert max_sign_up_step(e)[0] == SignUpStep.GOOGLE_OAUTH_CALLBACK_ERROR
    assert max_sign_up_step(e)[2] == 'no_access'
    record_sign_up_step(e, SignUpStep.ACCESS_INVITE_PAGE)
    db.session.rollback()
    assert max_sign_up_step(e)[0] == SignUpStep.GOOGLE_OAUTH_CALLBACK_ERROR
