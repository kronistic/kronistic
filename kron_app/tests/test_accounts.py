import pytest
from kron_app import db
from kron_app.models import User, Email, Contact, FixedEvent, Calendar, AvailabilityEvent
from kron_app.tests.helpers import mkuser, mkcal, mkfixedevent, mkavail, mkevent
from kron_app.accounts import remove
from kron_app.gcal_integration import GcalPushState

def test_remove(testdb, utcnow):
    users = []
    for i in range(3):
        u = mkuser(email=f'{i}@example.com', alias=f'_{i}@example.com', groups={'grp1': []})
        c = mkcal(u)
        mkfixedevent(c)
        mkavail(u, utcnow)
        users.append(u)
    for u in users:
        u.contacts.extend([u2 for u2 in users if u != u2])
    db.session.commit()
    assert User.query.count() == 3
    assert Calendar.query.count() == 6
    assert Email.query.count() ==  6
    assert FixedEvent.query.count() == 3
    assert Contact.query.count() == 6
    assert AvailabilityEvent.query.count() == 3
    u = users[0]
    remove(u)
    db.session.rollback()
    assert User.query.count() == 3
    assert Calendar.query.count() == 4
    assert Email.query.count() ==  6
    assert FixedEvent.query.count() == 2
    assert Contact.query.count() == 2
    assert AvailabilityEvent.query.count() == 2
    # check removed user
    assert u.is_removed
    assert u.calendars == []
    assert u.contacts == []
    assert u.availability_events == []
    assert u.groups == {}
    assert u.first_name == 'Deleted'
    assert u.last_name == 'User'
    assert u.name == 'Deleted User'
    assert all(email.address.endswith('@kronistic.com') for email in u.emails)
    assert u.gcal_push_id == None
    assert u.gcal_push_state == GcalPushState.OFF
    # further checks
    assert all(email.address.endswith('@example.com') for email in users[1].emails)
    assert all(email.address.endswith('@example.com') for email in users[2].emails)
    assert not users[1].is_removed
    assert not users[2].is_removed
    assert users[1].contacts == [users[2]]
    assert users[2].contacts == [users[1]]
    assert len(users[1].availability_events) == 1
    assert len(users[2].availability_events) == 1

def test_remove_fails_when_already_removed(testdb):
    u = mkuser()
    remove(u)
    with pytest.raises(AssertionError):
        remove(u)

def test_remove_fails_when_user_mentioned_in_groups(testdb):
    u = mkuser()
    mkuser(groups={'grp': [u.email]})
    with pytest.raises(AssertionError):
        remove(u)

def test_remove_fails_when_user_has_meetings(testdb):
    u = mkuser()
    mkevent(u, [u.id])
    with pytest.raises(AssertionError):
        remove(u)
