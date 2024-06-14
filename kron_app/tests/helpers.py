import json
from uuid import uuid4
from datetime import datetime, timedelta
from kron_app import db
from kron_app.utils import uid32
from kron_app.models import Attendance, User, Email, Calendar, Event, EventState, FixedEvent, Change, AvailabilityEvent, GcalPushState
from kron_app.kron_directives import parse_kron_directive
from kron_app.availability import is_naive_dt

def mins(m):
    return timedelta(minutes=m)

def hrs(h):
    return timedelta(hours=h)

def days(d):
    return timedelta(days=d)

def mkuser(email=None, alias=None, groups={}, setup_complete=True):
    if email is None:
        email = f'{uuid4().hex[0:8]}@kronistic.com'
    u = User()
    if type(email) == Email:
        u.primary_email = email
    else:
        u.email = email.lower()
    name = u.email.split('@')[0]
    u.first_name = name
    u.name = name
    u.setup_complete = setup_complete
    if u.setup_complete:
        u.setup_json = json.dumps(dict(days=[0,1,2,3,4],start_time=9,end_time=17))
    u.groups = groups
    u.tokens = '{}'
    c = Calendar()
    c.user = u
    c.gcal_id = 'primary'
    c.gcal_sync_token = 'dummy'
    u.gcal_push_id = f'{uid32()}@group.calendar.google.com'
    u.gcal_push_state = GcalPushState.ON
    if alias:
        u.emails.append(Email(address=alias))
    db.session.add(u,c)
    db.session.commit()
    return u

def mkinvite():
    e = Email()
    e.address = f'{uuid4().hex[0:8]}@example.com'
    e.uid = uid32()
    db.session.add(e)
    db.session.commit()
    return e

def add_attendees(event, attendees=[], optionalattendees=[], invitees=[], optionalinvitees=[]):
    for user_id in set(attendees+optionalattendees):
        add_attendee(event, User.query.get(user_id), optional=(user_id not in attendees))
    for email_id in set(invitees+optionalinvitees):
        email = Email.query.get(email_id)
        assert email.user is None, "email belongs to a user so can't be invitee"
        add_attendee(event, email, optional=(email_id not in invitees))

def add_attendee(event, user_or_email, optional=False, priority=Attendance.default_priority()):
    assert type(user_or_email) in (User, Email)
    email = user_or_email if type(user_or_email) == Email else user_or_email.primary_email
    assert email.user is None or email.user.primary_email == email, 'cannot add email alias'
    event.attendances.append(Attendance(email=email, creator=event.creator, optional=optional, priority=priority))

def delete_attendee(event, user_or_email):
    assert type(user_or_email) in (User, Email)
    email = user_or_email if type(user_or_email) == Email else user_or_email.primary_email
    a = next(a for a in event.attendances if a.email == email)
    a.deleted = True

def mkevent(creator, attendees=[], optionalattendees=[], invitees=[], optionalinvitees=[],
            length=timedelta(minutes=10), wstart=None, wlength=timedelta(days=7),
            freeze_horizon=timedelta(days=1)):
    if wstart is None:
        wstart = datetime.utcnow()
    creator_id = creator.id
    e = Event()
    e.title = 'My title'
    e.description = 'My description'
    e.creator = creator
    e.length = length
    e.tzname = 'UTC'
    e.window_start = wstart
    e.window_end = wstart + wlength
    e.window_start_local = wstart
    e.window_end_local = wstart + wlength
    e.freeze_horizon = freeze_horizon
    add_attendees(e, attendees, optionalattendees, invitees, optionalinvitees)
    db.session.add(e)
    db.session.commit()
    return e

# TODO: consolidate -- pick one default, and update tests to preserve
# set-up / context.

# it might be possible to avoid updating some tests if we know that
# they don't crucially rely on a specific value of freeze_horizon.

# it's not sufficient to just check that they don't fail with a
# different default. instead, we also need to know that the set of
# circumstances under which the test fails is preserved.

# This is used by runsolver(/extended) tests.
def mkevent_for_solver_tests(*args, **kwargs):
    if 'freeze_horizon' not in kwargs:
        kwargs['freeze_horizon'] = timedelta(minutes=60)
    return mkevent(*args, **kwargs)

def isinit(e):
    return (e.is_init() and
            e.draft_start is None and
            e.draft_end is None and
            e.draft_attendees == [])

def isunscheduled(e):
    return (e.is_unscheduled() and
            e.draft_start is None and
            e.draft_end is None and
            e.draft_attendees == [])

def isscheduled(e):
    return (e.is_scheduled() and
            e.draft_start is not None and
            e.draft_end is not None)

# TODO: this should maybe error if draft_attendees are not
# (optional)attendees.
def schedule(event, start, attendees):
    event.draft_start = start
    event.draft_end = start + event.length
    event.draft_attendees = attendees
    event.state = EventState.SCHEDULED
    db.session.commit()

def unschedule(event):
    event.draft_start = None
    event.draft_end = None
    event.draft_attendees = []
    event.state = EventState.UNSCHEDULED
    db.session.commit()

def mkclean(event):
    event.dirty = False
    db.session.commit()

def mkdirty(e):
    e.dirty = True
    db.session.commit()
    return e

def mkfinal(e):
    e.final = True
    db.session.commit()
    return e

def setpriority(event, user, priority):
    #find the attaendance for this user (email) and this meeting and set the priority
    a = Attendance.query.filter_by(event_id=event.id, email_id=user.primary_email_id).first()
    a.priority = priority
    db.session.commit()

def mkcal(u):
    c = Calendar()
    c.user = u
    c.gcal_id = uuid4()
    c.gcal_sync_token = 'dummy'
    db.session.add(c)
    db.session.commit()
    return c

def mkfixedevent(calendar_or_user, start_at=None, length=timedelta(hours=1), kron_directive=None):
    c = calendar_or_user.primary_calendar if type(calendar_or_user)==User else calendar_or_user
    if start_at is None:
        start_at = datetime.utcnow()
    k = FixedEvent()
    k.calendar = c
    k.all_day = False
    k.start_dt = start_at
    k.end_dt = start_at + length
    k.uid = uuid4()
    if kron_directive:
        k.kron_duty, k.costs = parse_kron_directive(kron_directive)
    else:
        k.kron_duty = False
    db.session.add(k)
    db.session.commit()
    return k

def mkavail(user, start_at, length=timedelta(hours=1), cost=0, tzname='UTC', recur=0):
    assert is_naive_dt(start_at)
    assert (type(recur) == int and recur >= 0) or recur == 'forever'
    assert length > timedelta()
    end_at = start_at + length
    recur_end_at = None if recur == 'forever' else end_at + timedelta(days=7)*recur
    a = AvailabilityEvent(user=user,
                          tzname=tzname,
                          start_at=start_at,
                          end_at=end_at,
                          recur_end_at=recur_end_at,
                          cost=cost)
    db.session.add(a)
    db.session.commit()
    return a

def mkspace(u, start_at, end_at):
    c = Change(start_at=start_at,
               end_at=end_at,
               users=[u.id],
               conflict=False)
    db.session.add(c)
    db.session.commit()
    return c

def mkconflict(u, start_at, end_at):
    c = Change(start_at=start_at,
               end_at=end_at,
               users=[u.id],
               conflict=True)
    db.session.add(c)
    db.session.commit()
    return c
