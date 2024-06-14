import json
from datetime import datetime
from enum import IntEnum, unique
from kron_app import db
from kron_app.models import User, Email

def find_user_by_email(address):
    q = db.select(User).join(User.emails) \
                       .filter(Email.address==address)
    return db.session.execute(q).scalar_one_or_none()

def find_user_by_primary_email(address):
    q = db.select(User).join(User.primary_email) \
                       .filter(Email.address==address)
    return db.session.execute(q).scalar_one_or_none()

@unique
class SignUpStep(IntEnum):
    ACCESS_INVITE_PAGE = 0
    ACCESS_SIGN_IN_PAGE = 1
    GOOGLE_OAUTH_REDIRECT = 2
    GOOGLE_OAUTH_CALLBACK_ERROR = 3

def record_sign_up_step(email_or_uid, step, extra_info=None):
    email = (email_or_uid
             if type(email_or_uid)==Email
             else email_or_uid and Email.query.filter_by(uid=email_or_uid).one_or_none())
    if email is None:
        return
    steps = json.loads(email.sign_up_steps_json)
    steps.append([step, int(datetime.utcnow().timestamp()), extra_info])
    email.sign_up_steps_json = json.dumps(steps)
    db.session.commit()

def max_sign_up_step(email):
    steps = [(SignUpStep(step), datetime.utcfromtimestamp(ts), extra_info)
             for step, ts, extra_info in json.loads(email.sign_up_steps_json)]
    return max(steps, default=None)
