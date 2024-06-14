import pytest
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from kron_app import db
from kron_app.tests.helpers import mkuser, mkinvite, mkevent, schedule, unschedule, add_attendee, delete_attendee
from kron_app.models import Email, Event, EventState, Series, Change, Attendance, AttendeeResponse
from kron_app.events import events_for, invited_to, build_event, build_rrule_series, update_event, expand_weekly, build_weekly_series, delete_event, move_from_pending, set_state, decline, populate_contacts, update_attendees, invitee_to_attendee_fixup, set_attendee_response

def event_data(u, **extra):
    return {**dict(creator=u,
                   length_in_mins=15,
                   tzname='UTC',
                   window_start_local = datetime(2022, 5, 2, 0, 0),
                   window_end_local = datetime(2022, 5, 6, 23, 59),
                   freeze_horizon_in_days = 1,
                   title = 'My meeting',
                   description = '',
                   location = '',
                   priority = None),
            **extra}

def event_to_dict(e, **extra):
    attrs = ('title description location length_in_mins tzname '
             'window_start_local window_end_local '
             'freeze_horizon_in_days priority').split()
    d = {**dict((attr, getattr(e, attr)) for attr in attrs), **extra}
    d['theattendees'] = [dict(email=a.email.address, optional=a.optional) for a in e.attendances if not a.deleted]
    return d

def test_new_event(testdb):
    u = mkuser()
    event = build_event(**event_data(u))
    db.session.commit()
    assert Event.query.count() == 1
    assert event.is_init()
    assert event.dirty

def test_new_pending_event(testdb):
    u = mkuser()
    event = build_event(**event_data(u, theattendees=[dict(email='you@example.com', optional=False)]))
    db.session.commit()
    assert Event.query.count() == 1
    assert event.is_pending()

def test_expand_weekly():
    lst = expand_weekly(datetime(2022, 5, 2, 9, 0),
                        datetime(2022, 5, 3, 17, 0),
                        2)
    assert lst == [(datetime(2022, 5, 2, 9, 0), datetime(2022, 5, 3, 17, 0)),
                   (datetime(2022, 5, 9, 9, 0), datetime(2022, 5, 10, 17, 0))]

def test_create_series(testdb):
    u = mkuser()
    # First event will have its window in BST, the second in GMT.
    data = event_data(u, tzname='Europe/London',
                      window_start_local=datetime(2022,10,24),
                      window_end_local=datetime(2022,10,29))
    build_weekly_series(data, 2)
    db.session.commit()
    assert Series.query.count() == 1
    series = Series.query.first()
    assert len(series.events) == 2
    events = Event.query.order_by('window_start').all()
    assert events[0].window_start_local == datetime(2022,10,24)
    assert events[0].window_end_local == datetime(2022,10,29)
    assert events[0].window_start == datetime(2022,10,23,23)
    assert events[0].window_end == datetime(2022,10,28,23)
    assert events[0].tzname == 'Europe/London'
    assert events[1].window_start_local == datetime(2022,10,31)
    assert events[1].window_end_local == datetime(2022,11,5)
    assert events[1].window_start == datetime(2022,10,31)
    assert events[1].window_end == datetime(2022,11,5)
    assert events[1].tzname == 'Europe/London'

def test_create_rrule_series(testdb):
    u = mkuser()
    # First event will have its window in BST, the second in GMT.
    data = event_data(u, tzname='Europe/London',
                      window_start_local=datetime(2022,10,24),
                      window_end_local=datetime(2022,10,29))
    build_rrule_series(data, "FREQ=WEEKLY;INTERVAL=1;COUNT=2")
    db.session.commit()
    assert Series.query.count() == 1
    series = Series.query.first()
    assert len(series.events) == 2
    events = Event.query.order_by('window_start').all()
    assert events[0].window_start_local == datetime(2022,10,24)
    assert events[0].window_end_local == datetime(2022,10,29)
    assert events[0].window_start == datetime(2022,10,23,23)
    assert events[0].window_end == datetime(2022,10,28,23)
    assert events[0].tzname == 'Europe/London'
    assert events[1].window_start_local == datetime(2022,10,31)
    assert events[1].window_end_local == datetime(2022,11,5)
    assert events[1].window_start == datetime(2022,10,31)
    assert events[1].window_end == datetime(2022,11,5)
    assert events[1].tzname == 'Europe/London'

def test_update_event_add_attendee(testdb):
    u = mkuser()
    v = mkuser()
    e = mkevent(u, attendees=[u.id])
    assert e.is_init()
    event_data = event_to_dict(e)
    event_data['theattendees'].append(dict(email=v.email, optional=False))
    made_pending, new_attendees, new_invitees = update_event(e, **event_data)
    assert e.is_init()
    assert e.dirty
    assert not made_pending
    assert new_attendees == [v.id]
    assert new_invitees == []

def test_update_event_add_invitee_to_init(testdb):
    u = mkuser()
    i = mkinvite()
    e = mkevent(u)
    assert e.is_init()
    event_data = event_to_dict(e)
    event_data['theattendees'].append(dict(email=i.address, optional=False))
    made_pending, new_attendees, new_invitees = update_event(e, **event_data)
    assert e.is_pending()
    assert not made_pending
    assert new_attendees == []
    assert new_invitees == [i.id]

def test_update_event_add_invitee_to_unscheduled(testdb):
    u = mkuser()
    i = mkinvite()
    e = mkevent(u)
    unschedule(e)
    assert e.is_unscheduled()
    event_data = event_to_dict(e)
    event_data['theattendees'].append(dict(email=i.address, optional=False))
    made_pending, new_attendees, new_invitees = update_event(e, **event_data)
    assert e.is_pending()
    assert not made_pending
    assert new_attendees == []
    assert new_invitees == [i.id]

def test_update_event_add_invitee_to_draft(testdb):
    u = mkuser()
    i = mkinvite()
    e = mkevent(u)
    schedule(e, datetime.utcnow(), [u.id])
    assert e.is_scheduled()
    assert Change.query.count() == 0
    event_data = event_to_dict(e)
    event_data['theattendees'].append(dict(email=i.address, optional=False))
    made_pending, new_attendees, new_invitees = update_event(e, **event_data)
    assert e.is_pending()
    assert made_pending
    assert new_attendees == []
    assert new_invitees == [i.id]
    assert Change.query.count() == 1
    change = Change.query.first()
    assert change.event == e

def test_update_event_add_back_declined_attendee(testdb):
    c = mkuser()
    u = mkuser()
    e = mkevent(c, attendees=[u.id])
    set_attendee_response(e, u, AttendeeResponse.NO)
    delete_attendee(e, u)
    db.session.commit()
    assert e.attendees == []
    event_data = event_to_dict(e)
    event_data['theattendees'].append(dict(email=u.email, optional=False))
    made_pending, new_attendees, new_invitees = update_event(e, **event_data)
    assert new_attendees == []

def test_delete_event(testdb):
    c = mkuser()
    e = mkevent(c)
    delete_event(e.id)
    db.session.rollback()
    assert e.state == EventState.DELETED

def test_delete_event_records_change(testdb):
    u = mkuser()
    e = mkevent(u)
    schedule(e, datetime.utcnow(), [u.id])
    assert e.is_scheduled()
    assert Change.query.count() == 0
    delete_event(e.id)
    db.session.rollback() # Ensure committed.
    assert e.state == EventState.DELETED
    assert Change.query.count() == 1

def test_update_attendees_normalizes_alias(testdb):
    u = mkuser(alias='u@foo.com')
    e = mkevent(u)
    assert len(u.emails) == 2
    update_attendees(e, [dict(email='u@foo.com', optional=False)])
    db.session.commit()
    assert e.attendees == [u.id]
    assert len(e.attendances) == 1
    assert e.attendances[0].email == u.primary_email

def test_update_attendees_no_dupes(testdb):
    c = mkuser()
    e = mkevent(c)
    update_attendees(e, [dict(email=c.email, optional=False), dict(email=c.email, optional=True)])
    db.session.commit()
    assert len(e.attendees+e.optionalattendees) == 1

def test_update_attendees_no_dupes2(testdb):
    c = mkuser(alias='c@foo.com')
    e = mkevent(c)
    update_attendees(e, [dict(email=c.email, optional=False), dict(email='c@foo.com', optional=True)])
    db.session.commit()
    assert len(e.attendees+e.optionalattendees) == 1

def test_update_attendees_add_attendee_is_case_insensitive(testdb):
    c = mkuser()
    e = mkevent(c)
    update_attendees(e, [dict(email=c.email.upper(), optional=False)])
    db.session.commit()
    assert e.attendees == [c.id]

def test_update_attendees_add_new_invitee_is_case_insensitive(testdb):
    c = mkuser()
    e = mkevent(c)
    update_attendees(e, [dict(email='Me@Example.Com', optional=False)])
    db.session.commit()
    assert len(e.invitees) == 1
    assert Email.query.get(e.invitees[0]).address == 'me@example.com'

def test_update_attendees_add_existing_invitee_is_case_insensitive(testdb):
    c = mkuser()
    i = mkinvite()
    e = mkevent(c)
    update_attendees(e, [dict(email=i.address.upper(), optional=False)])
    db.session.commit()
    assert e.invitees == [i.id]

def test_update_attendees_edit_attendee_is_case_insensitive(testdb):
    c = mkuser()
    e = mkevent(c, attendees=[c.id])
    update_attendees(e, [dict(email=c.email.upper(), optional=True)])
    db.session.commit()
    assert e.attendees == []
    assert e.optionalattendees == [c.id]

def test_update_attendees_edit_invitee_is_case_insensitive(testdb):
    c = mkuser()
    i = mkinvite()
    e = mkevent(c, invitees=[i.id])
    update_attendees(e, [dict(email=i.address.upper(), optional=True)])
    db.session.commit()
    assert e.invitees == []
    assert e.optionalinvitees == [i.id]

def test_update_attendees_delete_attendee(testdb):
    c = mkuser()
    e = mkevent(c, attendees=[c.id])
    update_attendees(e, [])
    db.session.commit()
    assert e.attendees == []

def test_invitee_to_attendee_fixup__nothing_to_do(testdb):
    u = mkuser()
    tosync = invitee_to_attendee_fixup(u, u.primary_email)
    assert tosync == []

# This exercises the new sign-up case. It's only setting of meeting
# state that is of interest in the case. (Moving invitee -> attendee
# happens automatically when adding the user to the email.)
def test_invitee_to_attendee_fixup__new_user(testdb):
    c = mkuser()
    i = mkinvite()
    j = mkinvite()
    e = mkevent(c, attendees=[c.id], invitees=[i.id, j.id])
    f = mkevent(c, attendees=[c.id], invitees=[j.id])
    g = mkevent(c, attendees=[c.id], optionalinvitees=[i.id])
    schedule(g, datetime.utcnow(), [c.id])
    set_state(e)
    set_state(f)
    set_state(g)
    db.session.commit()
    assert e.is_pending()
    assert f.is_pending()
    assert g.is_scheduled()
    assert Change.query.count() == 0
    # Simulate a new sign-up taking an invite as primary email.
    u = mkuser(email=i, setup_complete=False)
    assert not u.setup_complete
    tosync = invitee_to_attendee_fixup(u, u.primary_email)
    db.session.rollback()
    # Note, attended events always become pending because set-up isn't
    # complete for the new user.
    assert e.is_pending()
    assert f.is_pending()
    assert g.is_pending()
    assert tosync == [g.id]
    assert Change.query.count() == 1

# This tests the main two paths for the existing-user case. i.e. Merge
# (attendee and invitee) or re-point (invitee).
@pytest.mark.parametrize('already_attendee', [False, True])
def test_invitee_to_attendee_fixup__existing_user(testdb, already_attendee):
    c = mkuser()
    u = mkuser()
    i = mkinvite()
    e = mkevent(c, attendees=[c.id,u.id] if already_attendee else [c.id], invitees=[i.id])
    set_state(e)
    db.session.commit()
    assert e.is_pending()
    tosync = invitee_to_attendee_fixup(u, i)
    db.session.rollback()
    assert tosync == []
    assert e.is_init()
    assert set(e.attendees) == set([c.id,u.id])
    assert e.invitees == []
    assert len(e.attendances) == 2
    assert u.primary_email in (a.email for a in e.attendances)

def test_invitee_to_attendee_fixup__scheduled_events_become_init(testdb):
    c = mkuser()
    u = mkuser()
    i = mkinvite()
    e = mkevent(c, attendees=[c.id], optionalinvitees=[i.id])
    schedule(e, datetime.utcnow(), [c.id])
    assert e.is_scheduled()
    assert Change.query.count() == 0
    tosync = invitee_to_attendee_fixup(u, i)
    db.session.rollback()
    assert e.is_init()
    assert tosync == [e.id]
    assert Change.query.count() == 1
    assert e.attendees == [c.id]
    assert e.optionalattendees == [u.id]
    assert e.optionalinvitees == []

@pytest.mark.parametrize('invitee_deleted, attendee_deleted, expected_deleted, '
                         'invitee_optional, attendee_optional, expected_optional', [
    # Invitee and attendee present, merge opt/req.
    (False, False, False, False, False, False),
    (False, False, False, True, False, False),
    (False, False, False, False, True, False),
    (False, False, False, True, True, True),
    # Attendee was deleted, optionality of invitee remains.
    (False, True, False, False, False, False),
    (False, True, False, True, False, True),
    (False, True, False, False, True, False),
    (False, True, False, True, True, True),
    # Invitee was deleted, optionality of attendee remains.
    (True, False, False, False, False, False),
    (True, False, False, True, False, False),
    (True, False, False, False, True, True),
    (True, False, False, True, True, True),
    # Both deleted, so stay deleted (doesn't matter about optionality)
    (True, True, True, False, False, False),
])
def test_invitee_to_attendee_fixup__merge_attendances(
        testdb,
        invitee_deleted, attendee_deleted, expected_deleted,
        invitee_optional, attendee_optional, expected_optional):
    c = mkuser()
    u = mkuser()
    i = mkinvite()
    e = mkevent(c)
    db.session.add(Attendance(event=e, creator=c, email=u.primary_email, deleted=attendee_deleted, optional=attendee_optional))
    db.session.add(Attendance(event=e, creator=c, email=i, deleted=invitee_deleted, optional=invitee_optional))
    db.session.commit()
    invitee_to_attendee_fixup(u, i)
    db.session.rollback()
    assert len(e.attendances) == 1
    a = e.attendances[0]
    assert a.email == u.primary_email
    assert a.optional == expected_optional
    assert a.deleted == expected_deleted

def test_invitee_to_attendee_fixup__adds_contacts(testdb):
    n = mkuser()
    p = mkuser()
    e = mkuser()
    o = mkuser()
    i = mkinvite()
    event = mkevent(n, attendees=[n.id,e.id], optionalattendees=[p.id], invitees=[i.id])
    set_state(event)
    db.session.commit()
    assert event.is_pending()
    assert all(u.contacts == [] for u in [n,p,e,o])
    u = mkuser(email=i)
    invitee_to_attendee_fixup(u, u.primary_email)
    db.session.rollback()
    assert set(n.contacts) == {u}
    assert set(p.contacts) == {u}
    assert set(e.contacts) == {u}
    assert set(u.contacts) == {n,p,e}
    assert set(o.contacts) == set()

def test_invitee_to_attendee_fixup__circular_dependency_bug(testdb):
    c = mkuser()
    u = mkuser()
    i = mkinvite()
    e1 = mkevent(c, attendees=[c.id], invitees=[i.id])
    e2 = mkevent(c, attendees=[c.id], invitees=[i.id])
    set_state(e1)
    set_state(e2)
    db.session.commit()
    assert e1.is_pending()
    assert e2.is_pending()
    # This call would fall over with `CircularDependencyError` before
    # adding existence check prior to adding contacts...
    invitee_to_attendee_fixup(u, i)
    db.session.rollback()
    assert c.contacts == [u]
    assert u.contacts == [c]

def test_invitee_to_attendee_fixup__circular_dependency_bug_issue_654(testdb):
    u = mkuser()
    v = mkuser()
    w = mkuser(email='w@example.com')
    i = mkinvite()
    u.contacts = [v]
    v.contacts = [u]
    e1 = mkevent(u, attendees=[u.id], invitees=[i.id])
    e2 = mkevent(u, attendees=[v.id], invitees=[i.id])
    set_state(e1)
    set_state(e2)
    db.session.commit()
    assert e1.is_pending()
    assert e2.is_pending()
    # This raises a `CircularDependencyError` without `flush` added to
    # address #654.
    invitee_to_attendee_fixup(w, i)
    db.session.rollback()
    assert w.email == 'w@example.com'
    assert e1.is_init()
    assert e2.is_init()
    assert set(e1.attendees) == {u.id,w.id}
    assert set(e2.attendees) == {v.id,w.id}
    assert e1.invitees == []
    assert e2.invitees == []
    assert set(u.contacts) == {v,w}
    assert set(v.contacts) == {u,w}
    assert set(w.contacts) == {u,v}

def test_move_from_pending(testdb):
    c = mkuser() # creator
    u = mkuser() # new user
    v = mkuser(setup_complete=False) # another new user, waiting for calendar sync
    assert not v.setup_complete
    email = Email(address='me@example.com') # invite for some other email
    db.session.add(email)
    e = mkevent(c, attendees=[c.id, u.id])
    e2 = mkevent(c, attendees=[c.id], optionalattendees=[u.id])
    f = mkevent(c, attendees=[c.id, u.id], invitees=[email.id])
    g = mkevent(c, attendees=[c.id])
    h = mkevent(c, attendees=[c.id, u.id, v.id]) # blocked waiting for v's calendar to sync)
    e.state = EventState.PENDING
    e2.state = EventState.PENDING
    f.state = EventState.PENDING
    g.state = EventState.PENDING
    h.state = EventState.PENDING
    db.session.commit()
    assert e.is_pending()
    assert e2.is_pending()
    assert f.is_pending()
    assert g.is_pending()
    assert h.is_pending()
    result = move_from_pending(u)
    assert result == True
    assert e.is_init()
    assert e.dirty
    assert e2.is_init()
    assert e.dirty
    assert f.is_pending()
    assert g.is_pending()
    assert h.is_pending()

def test_decline(testdb):
    c = mkuser()
    email = Email(address='me@example.com')
    db.session.add(email)
    e = mkevent(c, attendees=[c.id], invitees=[email.id])
    f = mkevent(c, attendees=[c.id])
    db.session.commit()
    assert Event.query.count() == 2
    creators = decline(email)
    assert creators == [c]
    assert email.declined == [e.id]
    add_attendee(f, email)
    db.session.commit()
    creators = decline(email)
    assert creators == [c]
    assert len(email.declined) == 2
    assert set(email.declined) == set([e.id, f.id])

@pytest.mark.parametrize('optional', [True, False])
def test_attendee_declining_meeting(testdb, optional):
    c = mkuser()
    u = mkuser()
    e = mkevent(c)
    add_attendee(e, u, optional)
    schedule(e, e.window_start, [u.id])
    assert e.is_scheduled()
    set_attendee_response(e, u, AttendeeResponse.NO)
    db.session.commit()
    db.session.rollback()
    assert e.dirty
    assert len(e.attendances) == 1
    assert e.attendances[0].response == AttendeeResponse.NO
    assert e.is_scheduled() == optional

def test_populate_contacts(testdb):
    n = mkuser()
    e = mkuser()
    p = mkuser()
    o = mkuser()
    event = mkevent(n, attendees=[n.id,e.id], optionalattendees=[p.id])
    assert all(u.contacts == [] for u in [n,e,p,o])
    populate_contacts(event)
    db.session.rollback()
    assert set(n.contacts) == {e,p}
    assert set(e.contacts) == {n,p}
    assert set(p.contacts) == {n,e}
    assert set(o.contacts) == set()

def test_no_duplicate_attendees(testdb):
    c = mkuser()
    e = mkevent(c, attendees=[c.id])
    add_attendee(e, c)
    with pytest.raises(IntegrityError) as excinfo:
        db.session.commit()

@pytest.mark.parametrize('include_past', [False, True])
def test_events_for(testdb, include_past):
    n = mkuser()
    p = mkuser()
    e1 = mkevent(n, attendees=[])
    e2 = mkevent(p, attendees=[n.id])
    e3 = mkevent(p, attendees=[n.id])
    e4 = mkevent(p, attendees=[n.id])
    e5 = mkevent(p, attendees=[n.id])
    delete_attendee(e3, n)
    set_attendee_response(e4, n, AttendeeResponse.NO)
    e5.state = EventState.PAST
    db.session.commit
    assert set(events_for(n, include_past).all()) == {e1,e2,e5} if include_past else {e1,e2}

def test_invited_to(testdb):
    c = mkuser()
    i = mkinvite()
    e1 = mkevent(c, invitees=[])
    e2 = mkevent(c, invitees=[i.id])
    e3 = mkevent(c, invitees=[i.id])
    delete_attendee(e3, i)
    assert set(invited_to(i)) == {e2}
