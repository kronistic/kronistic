import sys
import os.path
from datetime import timedelta
from contextlib import contextmanager
from flask import url_for as flask_url_for
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from kron_app import app
from kron_app.events import events_for
from kron_app.utils import from_utc_to_s
from kron_app.templates.helpers import fmt_available_time, ext_url_for
from kron_app.models import User, AttendeeResponse


# This is most of what we need for #379.

# However, this requires `SERVER_NAME` to be set, and that potentially
# interacts with session cookie handling, so I don't want to change
# that with out checking that doing so doesn't break things.

@contextmanager
def ctx():
    """Set-up the appropriate context to allow `url_for` to be used from email template."""
    with app.app_context(), app.test_request_context():
        yield
ctx = ctx()

# def url_for(*args, **kwargs):
#     kwargs['_external'] = True
#     kwargs['_scheme'] = 'https'
#     return flask_url_for(*args, **kwargs)

# Local copy of `url_for`, used in footer.
def url_for(action):
    hostname = app.config['HOSTNAME']
    if action == 'add_meeting':
        return f'https://{hostname}/meetings/new'
    elif action == 'meetings':
        return f'https://{hostname}/meetings'
    else:
        raise Exception('unhandled action')

MAIL_TEMPLATE_DIR = os.path.join(app.root_path, app.template_folder, 'mail')

jinja_env = Environment(
    loader=FileSystemLoader(MAIL_TEMPLATE_DIR),
    undefined=StrictUndefined,
    autoescape=select_autoescape(['html'])
)
jinja_env.globals = dict(url_for=url_for, ext_url_for=ext_url_for)

def render(fn, **kwargs):
    return jinja_env.get_template(fn).render(**kwargs)

def test(recipient):
    return (recipient,
            'Test email from kronistic',
            'Hello, world!')

def invite_to_meeting(event, email):
    INVITE_UID_KEY='_'
    creator = event.creator
    invite_url = f'https://{app.config["HOSTNAME"]}/invite?{INVITE_UID_KEY}={email.uid}'
    alias_url = f'https://{app.config["HOSTNAME"]}/alias?{INVITE_UID_KEY}={email.uid}'
    subject = f'Use Kronistic to schedule "{event.title}"'
    body = render('invite_to_meeting.txt',
                  creator=creator,
                  invite_url=invite_url,
                  alias_url=alias_url)
    return email.address, subject, body

def invite_declined(user, email):
    subject = f'Attendee declined to use Kronistic'
    body = render('invite_declined.txt', user=user, email=email)
    return user.email, subject, body

def meeting_declined(event, user):
    # Note that a whole series of meetings may have been declined, in
    # which case `event` is a just the first meeting of the series.
    # The email notification intentionally glosses over this detail.
    attendance = next(a for a in event.attendances if a.email.user == user)
    assert attendance.response == AttendeeResponse.NO, 'not declined'
    meetings_url = f'https://{app.config["HOSTNAME"]}/meetings'
    subject = f'{user.name} declined your Kronistic meeting "{event.title}"'
    body = render('meeting_declined.txt', event=event, user=user, meetings_url=meetings_url)
    return event.creator.email, subject, body

def new_meeting(event, user):
    subject = f'New Kronistic meeting "{event.title}"'
    meetings_url = f'https://{app.config["HOSTNAME"]}/meetings'
    body = render('new_meeting.txt', event=event, meetings_url=meetings_url)
    return user.email, subject, body

def welcome(user):
    assert user.setup_data is not None, 'expected user to have setup data'
    events = events_for(user).all()
    def find(cond):
        return next((e for e in events if cond(e)), None)
    event = (find(lambda e: e.is_init() or e.is_scheduled()) or
             find(lambda e: e.is_pending()))
    meetings_url = f'https://{app.config["HOSTNAME"]}/meetings'
    new_meeting_url = f'https://{app.config["HOSTNAME"]}/meetings/new'
    profile_url = f'https://{app.config["HOSTNAME"]}/profile'
    meeting_url = f'https://{app.config["HOSTNAME"]}/meeting/{event.id}' if event else None
    availability_url = f'https://{app.config["HOSTNAME"]}/availability'
    subject = 'Welcome to Kronistic!'
    body = render('welcome.txt',
                  user=user,
                  event=event,
                  profile_url=profile_url,
                  meeting_url=meeting_url,
                  meetings_url=meetings_url,
                  new_meeting_url=new_meeting_url,
                  availability_url=availability_url,
                  fmt_available_time=fmt_available_time)
    return (user.email, subject, body)

def meeting_unscheduled(event):
    creator = event.creator
    meeting_help_url = f'https://{app.config["HOSTNAME"]}/meeting/{event.id}/fixit'
    subject = f'Cannot schedule Kronistic meeting "{event.title}"'
    body = render('meeting_unscheduled.txt',
                  event=event,
                  meeting_help_url=meeting_help_url)
    return creator.email, subject, body

def meeting_finalized(user, event):
    subject = f'Kronistic meeting "{event.title}" time finalized'
    start_at = from_utc_to_s(event.draft_start, user.tz)
    meetings_url = f'https://{app.config["HOSTNAME"]}/meetings'
    body = render('meeting_finalized.txt',
                  user=user,
                  event=event,
                  start_at=start_at,
                  meetings_url=meetings_url)
    return (user.email, subject, body)

def meeting_rescheduled(user, event):
    subject = f'Rescheduling Kronistic meeting "{event.title}"'
    start_at = from_utc_to_s(event.draft_start, user.tz)
    body = render('meeting_rescheduled.txt', event=event, start_at=start_at)
    return (user.email, subject, body)

def kalendar_repair(user):
    subject = f'Kronistic Calendar'
    profile_url = f'https://{app.config["HOSTNAME"]}/profile'
    body = render('kalendar_repair.txt', user=user, profile_url=profile_url)
    return (user.email, subject, body)

if __name__ == '__main__':
    if not len(sys.argv) == 2:
        print('Usage: mail.py <recipient>')
        exit()
    from kron_app.smtp import sendmail
    sendmail(test(sys.argv[1]))
