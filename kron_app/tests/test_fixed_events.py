import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from kron_app import db
from kron_app.tests.helpers import mkuser, mkevent, schedule, unschedule
from kron_app.models import FixedEvent, Change
from kron_app.run_solver import get_fixed_events
from kron_app.changes import record_all_day_event_changes

@pytest.fixture(scope='function', autouse=True)
def autotestdb(testdb):
    pass

def mkallday(user, date, length):
    k = FixedEvent()
    k.calendar = user.primary_calendar
    k.all_day = True
    k.start_dt = date
    k.end_dt = date + timedelta(days=length)
    k.uid = uuid4()
    k.kron_duty = False
    db.session.add(k)
    db.session.commit()
    return k

def test_all_day_overlapping_start():
    u = mkuser()
    assert u.tzname == 'America/Los_Angeles'
    e = mkallday(u, datetime(2022, 5, 1), 1)
    wsstart = e.end_at - timedelta(hours=1)
    wsend = wsstart + timedelta(days=1)
    fixed_events = get_fixed_events(wsstart, wsend, [u.id])
    assert fixed_events == [e]

def test_all_day_overlapping_end():
    u = mkuser()
    assert u.tzname == 'America/Los_Angeles'
    e = mkallday(u, datetime(2022, 5, 1), 1)
    wsend = e.start_at + timedelta(hours=1)
    wsstart = wsend - timedelta(days=1)
    fixed_events = get_fixed_events(wsstart, wsend, [u.id])
    assert fixed_events == [e]

def test_all_day_not_overlapping_start():
    u = mkuser()
    assert u.tzname == 'America/Los_Angeles'
    e = mkallday(u, datetime(2022, 5, 1), 1)
    wsstart = e.end_at + timedelta(hours=1)
    wsend = wsstart + timedelta(days=1)
    fixed_events = get_fixed_events(wsstart, wsend, [u.id])
    assert fixed_events == []

def test_all_day_not_overlapping_end():
    u = mkuser()
    assert u.tzname == 'America/Los_Angeles'
    e = mkallday(u, datetime(2022, 5, 1), 1)
    wsend = e.start_at - timedelta(hours=1)
    wsstart = wsend - timedelta(days=1)
    fixed_events = get_fixed_events(wsstart, wsend, [u.id])
    assert fixed_events == []

def test_all_day_event_start_end_at():
    u = mkuser()
    u.tzname = 'Europe/London'
    db.session.commit()
    # Local time is UTC
    e1 = mkallday(u, datetime(2022, 1, 1), 1)
    assert e1.start_at == datetime(2022, 1, 1, 0, 0)
    assert e1.end_at == datetime(2022, 1, 2, 0, 0)
    # Local time is BST
    e2 = mkallday(u, datetime(2022, 5, 2), 1)
    assert e2.start_at == datetime(2022, 5, 1, 23, 0)
    assert e2.end_at == datetime(2022, 5, 2, 23, 0)

def test_record_all_day_event_changes():
    utcnow = datetime.utcnow()
    c = mkuser('c@kronistic.com')
    u = mkuser('u@kronistic.com')
    e1 = mkevent(c, [c.id,u.id])
    e2 = mkevent(c, [c.id,u.id])
    e3 = mkevent(c, [c.id,u.id])
    schedule(e1, utcnow, e1.attendees)
    schedule(e2, utcnow+timedelta(days=2), e2.attendees)
    unschedule(e3)
    f = mkallday(c, utcnow, 1)
    mkallday(u, utcnow, 1)
    mkallday(c, utcnow-timedelta(days=7), 1)
    mkallday(u, utcnow-timedelta(days=7), 1)
    mkallday(c, utcnow+timedelta(days=7), 1)
    mkallday(u, utcnow+timedelta(days=7), 1)
    assert Change.query.count() == 0
    assert FixedEvent.query.filter_by(dirty=True).count() == 0
    record_all_day_event_changes(c)
    db.session.commit()
    assert Change.query.count() == 1
    assert FixedEvent.query.filter_by(dirty=True).count() == 1
    assert FixedEvent.query.filter_by(dirty=True).first() == f
