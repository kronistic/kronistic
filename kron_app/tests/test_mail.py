import pytest
from datetime import datetime, timedelta
from kron_app import db
from kron_app.tests.helpers import mkuser, mkinvite, mkevent, schedule, add_attendee
from kron_app.models import Event, EventState, AttendeeResponse
from kron_app.events import set_attendee_response
import kron_app.mail as mail
from kron_app.smtp import sendmail

def test_invite_to_meeting(testdb):
    e = mkevent(mkuser())
    i = mkinvite()
    m = mail.invite_to_meeting(e, i)
    sendmail(m)
    email, subject, body = m
    assert email == i.address
    assert type(subject) == str
    assert type(body) == str

def test_invite_declined(testdb):
    c = mkuser()
    i = mkinvite()
    m = mail.invite_declined(c, i)
    sendmail(m)
    email, subject, body = m
    assert email == c.email
    assert type(subject) == str
    assert type(body) == str

def test_meeting_declined(testdb):
    c = mkuser()
    u = mkuser()
    e = mkevent(c, attendees=[u.id])
    set_attendee_response(e, u, AttendeeResponse.NO)
    db.session.commit()
    m = mail.meeting_declined(e, u)
    sendmail(m)
    email, subject, body = m
    assert email == c.email
    assert type(subject) == str
    assert type(body) == str


def test_new_meeting(testdb):
    c = mkuser()
    u = mkuser()
    e = mkevent(c, attendees=[u.id])
    m = mail.new_meeting(e, u)
    sendmail(m)
    email, subject, body = m
    assert email == u.email
    assert type(subject) == str
    assert type(body) == str

def test_welcome_no_meeting(testdb):
    u = mkuser()
    m = mail.welcome(u)
    sendmail(m)
    email, subject, body = m
    assert email == u.email
    assert type(subject) == str
    assert type(body) == str
    assert "get started by making" in body.lower()

SCHEDULING_STATUS = 'is being scheduled'
PENDING_STATUS = 'will be scheduled'
@pytest.mark.parametrize('state, expected', [
    (EventState.INIT, SCHEDULING_STATUS),
    (EventState.SCHEDULED, SCHEDULING_STATUS),
    (EventState.PENDING, PENDING_STATUS)
])
def test_welcome_meeting_in_init(testdb, state, expected):
    u = mkuser()
    c = mkuser()
    dummy = mkevent(c, attendees=[c.id,u.id])
    dummy.state = EventState.UNSCHEDULED
    e = mkevent(c, attendees=[c.id,u.id])
    e.state = state
    db.session.commit()
    m = mail.welcome(u)
    sendmail(m)
    email, subject, body = m
    assert email == u.email
    assert type(subject) == str
    assert type(body) == str
    assert expected.lower() in body.lower()

def test_meeting_unscheduled(testdb):
    c = mkuser()
    e = mkevent(c, attendees=[c.id])
    e.state = EventState.UNSCHEDULED
    db.session.commit()
    m = mail.meeting_unscheduled(e)
    sendmail(m)
    email, subject, body = m
    assert email == c.email
    assert type(subject) == str
    assert type(body) == str

def test_meeting_finalized(testdb):
    c = mkuser()
    e = mkevent(c)
    schedule(e, e.window_start, [c.id])
    m = mail.meeting_finalized(c, e)
    sendmail(m)
    email, subject, body = m
    assert email == c.email
    assert type(subject) == str
    assert type(body) == str

def test_meeting_rescheduled(testdb):
    c = mkuser()
    e = mkevent(c)
    schedule(e, e.window_start, [c.id])
    m = mail.meeting_rescheduled(c, e)
    sendmail(m)
    email, subject, body = m
    assert email == c.email
    assert type(subject) == str
    assert type(body) == str

def test_kalendar_repair(testdb):
    u = mkuser()
    m = mail.kalendar_repair(u)
    sendmail(m)
    email, subject, body = m
    assert email == u.email
    assert type(subject) == str
    assert type(body) == str
