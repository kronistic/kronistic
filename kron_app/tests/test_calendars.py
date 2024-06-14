import pytest
from sqlalchemy.exc import IntegrityError
from kron_app import db
from kron_app.utils import ids
from kron_app.tests.helpers import mkuser, mkevent, schedule, mkcal, mkfixedevent as mkfixed
from kron_app.models import Calendar, Change, FixedEvent
from kron_app.calendars import delete_calendar

def test_delete_empty_calendar(testdb):
    u = mkuser()
    c = mkcal(u)
    db.session.commit()
    assert Calendar.query.count() == 2
    assert Change.query.count() == 0
    delete_calendar(c)
    db.session.commit()
    assert Calendar.query.count() == 1
    assert Change.query.count() == 0

def test_delete_calendar(testdb):
    u = mkuser()
    c = mkcal(u)
    other = mkcal(mkuser())
    f = mkfixed(c)
    mkfixed(other)
    db.session.commit()
    cid = c.id
    fid = f.id
    assert Calendar.query.count() == 4
    assert Change.query.count() == 0
    assert FixedEvent.query.count() == 2
    delete_calendar(c)
    db.session.commit()
    assert Calendar.query.count() == 3
    assert cid not in ids(Calendar.query.all())
    assert Change.query.count() == 1
    assert FixedEvent.query.count() == 1
    assert fid not in ids(FixedEvent.query.all())
    change = Change.query.first()
    assert not change.conflict
