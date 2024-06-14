import pytest
from datetime import datetime, timedelta
from kron_app.models import AvailabilityEvent as AEvent, Change
from kron_app.availability import get_overlapping, clear_window, clear_window_unbounded, get_bitmap, set_bitmap, get_events_bitmap, get_meetings_bitmap, record_changes, is_naive_dt, add_core_availability
from kron_app.availability import EventBitmap, UNAVAILABLE
from kron_app.tests.helpers import mkuser, mkevent, mkfixedevent, mkavail, schedule, days, hrs, mins
from kron_app import db

F = 0 # available (free)
I = 1 # if needed
B = UNAVAILABLE # unavailable (busy)

@pytest.fixture(scope='function', autouse=True)
def autotestdb(testdb):
    pass

def test_get_overlapping__trivial(utcnow):
    u = mkuser()
    assert get_overlapping(utcnow, utcnow+days(7), [u.id]) == []

def test_get_overlapping__utc_not_recurring(utcnow):
    u = mkuser()
    e1 = mkavail(u, utcnow, hrs(1))
    e2 = mkavail(u, utcnow+hrs(2), hrs(1))
    es = get_overlapping(utcnow, utcnow+days(1), [u.id])
    assert len(es) == 2
    es = get_overlapping(utcnow-days(1), utcnow, [u.id])
    assert len(es) == 0
    es = get_overlapping(utcnow, utcnow+days(1), [0])
    assert len(es) == 0

def test_get_overlapping__utc_recur_indefinitely(utcnow):
    u = mkuser()
    e1 = mkavail(u, utcnow, hrs(1), recur='forever')
    es = get_overlapping(utcnow, utcnow, [u.id])
    assert len(es) == 0
    es = get_overlapping(utcnow, utcnow+days(7), [u.id])
    assert len(es) == 1
    es = get_overlapping(utcnow, utcnow+days(14), [u.id])
    assert len(es) == 2
    assert es[0].start_at == utcnow
    assert es[0].end_at == es[0].start_at + hrs(1)
    assert es[1].start_at == utcnow + days(7)
    assert es[1].end_at == es[1].start_at + hrs(1)

def test_get_overlapping__utc_recur_indefinitely_boundaries(utcnow):
    u = mkuser()
    e1 = mkavail(u, utcnow, hrs(1), recur='forever')
    es = get_overlapping(utcnow-mins(5), utcnow+mins(5), [u.id])
    assert len(es) == 1
    es = get_overlapping(utcnow+mins(25), utcnow+mins(35), [u.id])
    assert len(es) == 1
    es = get_overlapping(utcnow+mins(55), utcnow+mins(65), [u.id])
    assert len(es) == 1
    es = get_overlapping(utcnow-mins(10), utcnow-mins(5), [u.id])
    assert len(es) == 0
    es = get_overlapping(utcnow+mins(70), utcnow+mins(75), [u.id])
    assert len(es) == 0

def test_get_overlapping__utc_recur_finitely(utcnow):
    u = mkuser()
    e1 = mkavail(u, utcnow, hrs(1), recur=1)
    es = get_overlapping(utcnow, utcnow+days(7), [u.id])
    assert len(es) == 1
    es = get_overlapping(utcnow, utcnow+days(14), [u.id])
    assert len(es) == 2
    es = get_overlapping(utcnow, utcnow+days(21), [u.id])
    assert len(es) == 2




def test_clear_window_bounded__utc_one_off_before():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1), hrs(1)) # 0:00 - 1:00
    clear_window(datetime(2023, 1, 1, 2), datetime(2023, 1, 2), u.id)
    db.session.commit()
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 1)
    assert e.recur_end_at == datetime(2023, 1, 1, 1)
    assert e.tzname == 'UTC'

def test_clear_window_bounded__utc_one_off_overlap_start():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1), hrs(1)) # 0:00 - 1:00
    clear_window(datetime(2023, 1, 1, 0, 30), datetime(2023, 1, 2), u.id)
    db.session.commit()
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 0, 30)
    assert e.end_at == datetime(2023, 1, 1, 0, 30)
    assert e.tzname == 'UTC'

def test_clear_window_bounded__utc_one_off_during():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1), hrs(1)) # 0:00 - 1:00
    clear_window(datetime(2023, 1, 1), datetime(2023, 1, 2), u.id)
    db.session.commit()
    assert AEvent.query.count() == 0

def test_clear_window_bounded__utc_one_off_overlap_end():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1)) # 1:00 - 2:00
    clear_window(datetime(2023, 1, 1), datetime(2023, 1, 1, 1, 30), u.id)
    db.session.commit()
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1, 1, 30)
    assert e.end_at == datetime(2023, 1, 1, 2)
    assert e.recur_end_at == datetime(2023, 1, 1, 2)
    assert e.tzname == 'UTC'

def test_clear_window_bounded__utc_one_off_after():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1)) # 1:00 - 2:00
    clear_window(datetime(2023, 1, 1), datetime(2023, 1, 1, 1), u.id)
    db.session.commit()
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 2)
    assert e.recur_end_at == datetime(2023, 1, 1, 2)
    assert e.tzname == 'UTC'

@pytest.mark.parametrize('recur', [3, 'forever'])
def test_clear_window_bounded__utc_recurring(recur):
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1), hrs(1), recur=recur)
    clear_window(datetime(2023, 1, 8, 0, 30), datetime(2023, 1, 15, 0, 30), u.id)
    db.session.commit()
    assert AEvent.query.count() == 4
    es = AEvent.query.order_by('start_at').all()
    assert es[0].start_at == datetime(2023, 1, 1)
    assert es[0].end_at == datetime(2023, 1, 1, 1)
    assert es[0].recur_end_at == datetime(2023, 1, 1, 1)
    assert es[0].tzname == 'UTC'
    assert es[1].start_at == datetime(2023, 1, 8)
    assert es[1].end_at == datetime(2023, 1, 8, 0, 30)
    assert es[1].recur_end_at == datetime(2023, 1, 8, 0, 30)
    assert es[1].tzname == 'UTC'
    assert es[2].start_at == datetime(2023, 1, 15, 0, 30)
    assert es[2].end_at == datetime(2023, 1, 15, 1)
    assert es[2].recur_end_at == datetime(2023, 1, 15, 1)
    assert es[2].tzname == 'UTC'
    assert es[3].start_at == datetime(2023, 1, 22)
    assert es[3].end_at == datetime(2023, 1, 22, 1)
    assert es[3].recur_end_at == None if recur =='forever' else datetime(2023, 1, 22, 1)
    assert es[3].tzname == 'UTC'

def test_clear_window_bounded__london_one_off():
    u = mkuser()
    mkavail(u, datetime(2023, 6, 9, 0), hrs(1), tzname='Europe/London')
    mkavail(u, datetime(2023, 6, 9, 2), hrs(2), tzname='Europe/London')
    mkavail(u, datetime(2023, 6, 9, 5), hrs(1), tzname='Europe/London')
    mkavail(u, datetime(2023, 6, 9, 7), hrs(2), tzname='Europe/London')
    mkavail(u, datetime(2023, 6, 9, 10), hrs(1), tzname='Europe/London')
    clear_window(datetime(2023, 6, 9, 2), datetime(2023, 6, 9, 7), u.id)
    db.session.commit()
    assert AEvent.query.count() == 4
    es = AEvent.query.order_by('start_at').all()
    for e, (start_hr, end_hr) in zip(es, [(0, 1), (2, 3), (8, 9), (10, 11)]):
        assert e.start_at == datetime(2023, 6, 9, start_hr)
        assert e.end_at == datetime(2023, 6, 9, end_hr)
        assert e.recur_end_at == datetime(2023, 6, 9, end_hr)
        assert e.tzname == 'Europe/London'



def test_clear_window_unbounded__utc_one_off_before():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1), hrs(1)) # midnight - 1am
    clear_window_unbounded(datetime(2023, 1, 1, 2), u.id) # from 2am
    db.session.commit()
    # no change
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 1)
    assert e.recur_end_at == datetime(2023, 1, 1, 1)
    assert e.tzname == 'UTC'

def test_clear_window_unbounded__utc_one_off_overlapping():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1)) # 1am - 2am
    clear_window_unbounded(datetime(2023, 1, 1, 1, 30), u.id) # from 1:30am
    db.session.commit()
    # split
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 1, 30)
    assert e.recur_end_at == datetime(2023, 1, 1, 1, 30)
    assert e.tzname == 'UTC'

def test_clear_window_unbounded__utc_one_off_after():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 2), hrs(1)) # 2am - 3am
    clear_window_unbounded(datetime(2023, 1, 1, 1), u.id) # from 1am
    db.session.commit()
    # deleted
    assert AEvent.query.count() == 0 # the underlying record should be removed

def test_clear_window_unbounded__utc_recurring_finitely_finish_before():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 2), hrs(1), recur=3) # 2am - 3am
    clear_window_unbounded(datetime(2023, 1, 23), u.id)
    db.session.commit()
    # no change
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1, 2)
    assert e.end_at == datetime(2023, 1, 1, 3)
    assert e.recur_end_at == e.end_at + timedelta(days=7)*3
    assert e.tzname == 'UTC'

def test_clear_window_unbounded__utc_recurring_finitely_overlapping_boundary():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 2), hrs(1), recur=3) # 2am - 3am
    clear_window_unbounded(datetime(2023, 1, 8, 2, 30), u.id)
    db.session.commit()
    # adjusted original + split
    assert AEvent.query.count() == 2
    es = AEvent.query.order_by('start_at').all()
    assert es[0].start_at == datetime(2023, 1, 1, 2)
    assert es[0].end_at == datetime(2023, 1, 1, 3)
    assert es[0].recur_end_at == datetime(2023, 1, 1, 3)
    assert es[0].tzname == 'UTC'
    assert es[1].start_at == datetime(2023, 1, 8, 2)
    assert es[1].end_at == datetime(2023, 1, 8, 2, 30)
    assert es[1].recur_end_at == datetime(2023, 1, 8, 2, 30)
    assert es[1].tzname == 'UTC'

def test_clear_window_unbounded__utc_recurring_finitely_starting_after():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 2), hrs(1), recur=3) # 2am - 3am
    clear_window_unbounded(datetime(2023, 1, 1), u.id)
    db.session.commit()
    # deleted
    assert AEvent.query.count() == 0

def test_clear_window_unbounded__utc_recurring_forever_start_before_no_overlap():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1), recur='forever') # 1am - 2am
    clear_window_unbounded(datetime(2023, 1, 1, 3), u.id) # from 3am
    db.session.commit()
    # adjusted recur_end
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 2)
    assert e.recur_end_at == datetime(2023, 1, 1, 2)

def test_clear_window_unbounded__utc_recurring_forever_start_before_with_overlap():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1), recur='forever') # 1am - 2am
    clear_window_unbounded(datetime(2023, 1, 8, 1, 30), u.id) # note: splits 2nd occurrence
    db.session.commit()
    # adjusted original + split
    assert AEvent.query.count() == 2
    es = AEvent.query.order_by('start_at').all()
    assert es[0].start_at == datetime(2023, 1, 1, 1)
    assert es[0].end_at == datetime(2023, 1, 1, 2)
    assert es[0].recur_end_at == datetime(2023, 1, 1, 2)
    assert es[0].tzname == 'UTC'
    assert es[1].start_at == datetime(2023, 1, 8, 1)
    assert es[1].end_at == datetime(2023, 1, 8, 1, 30)
    assert es[1].recur_end_at == datetime(2023, 1, 8, 1, 30)
    assert es[1].tzname == 'UTC'

def test_clear_window_unbounded__utc_recurring_forever_start_overlapping():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1), recur='forever') # 1am - 2am
    clear_window_unbounded(datetime(2023, 1, 1, 1, 30), u.id) # note: splits first occurrence
    db.session.commit()
    # split only
    assert AEvent.query.count() == 1
    e = AEvent.query.first()
    assert e.start_at == datetime(2023, 1, 1, 1)
    assert e.end_at == datetime(2023, 1, 1, 1, 30)
    assert e.recur_end_at == datetime(2023, 1, 1, 1, 30)
    assert e.tzname == 'UTC'

def test_clear_window_unbounded__utc_recurring_forever_start_after():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1), recur='forever') # 1am - 2am
    clear_window_unbounded(datetime(2023, 1, 1, 0, 30), u.id) # 0:30 am
    db.session.commit()
    # deleted
    assert AEvent.query.count() == 0

def test_clear_window_unbounded__london_one_off():
    u = mkuser()
    mkavail(u, datetime(2023, 6, 9, 0), hrs(1), tzname='Europe/London')
    mkavail(u, datetime(2023, 6, 9, 2), hrs(2), tzname='Europe/London')
    mkavail(u, datetime(2023, 6, 9, 5), hrs(1), tzname='Europe/London')
    clear_window_unbounded(datetime(2023, 6, 9, 2), u.id)
    db.session.commit()
    assert AEvent.query.count() == 2
    es = AEvent.query.order_by('start_at').all()
    for e, (start_hr, end_hr) in zip(es, [(0, 1), (2, 3)]):
        assert e.start_at == datetime(2023, 6, 9, start_hr)
        assert e.end_at == datetime(2023, 6, 9, end_hr)
        assert e.recur_end_at == datetime(2023, 6, 9, end_hr)
        assert e.tzname == 'Europe/London'

def test_clear_window_unbounded__london_recurring_forever():
    u = mkuser()
    mkavail(u, datetime(2023, 6, 9), hrs(2), tzname='Europe/London', recur='forever') # note: starts in bst
    clear_window_unbounded(datetime(2023, 12, 8, 1), u.id) # clear starts after dst boundary
    db.session.commit()
    assert AEvent.query.count() == 2
    es = AEvent.query.order_by('start_at').all()
    assert es[0].start_at == datetime(2023, 6, 9)
    assert es[0].end_at == datetime(2023, 6, 9, 2)
    assert es[0].recur_end_at == datetime(2023, 12, 1, 2)
    assert es[0].tzname == 'Europe/London'
    assert es[1].start_at == datetime(2023, 12, 8)
    assert es[1].end_at == datetime(2023, 12, 8, 1)
    assert es[1].recur_end_at == datetime(2023, 12, 8, 1)
    assert es[1].tzname == 'Europe/London'




def test_get_bitmap():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1), hrs(2), tzname='UTC') # overlapping start
    mkavail(u, datetime(2023, 1, 1, 2, 16), mins(28), tzname='UTC') # off-grain
    mkavail(u, datetime(2023, 1, 1, 3, 30), hrs(1), tzname='UTC') # overlapping end
    data = get_bitmap(u, datetime(2023, 1, 1, 1), 'UTC', 12)
    assert len(data) == 12
    assert data == [F,F,F,F,B,F,F,B,B,B,F,F]

def test_get_bitmap__recurring_availability_london():
    u = mkuser()
    # availability in london time
    mkavail(u, datetime(2023, 1, 1, 1, 30), hrs(1), tzname='Europe/London', recur='forever')
    # viewed from utc
    data = get_bitmap(u, datetime(2023, 1, 1), 'UTC', 12)
    assert len(data) == 12
    assert data == [B,B,B,B,B,B,F,F,F,F,B,B]
    # shifts during bst
    data = get_bitmap(u, datetime(2023, 4, 30), 'UTC', 12)
    assert len(data) == 12
    assert data == [B,B,F,F,F,F,B,B,B,B,B,B]
    # viewed from europe is at fixed time
    data = get_bitmap(u, datetime(2023, 1, 1), 'Europe/London', 12)
    assert len(data) == 12
    assert data == [B,B,B,B,B,B,F,F,F,F,B,B]
    data = get_bitmap(u, datetime(2023, 4, 30), 'Europe/London', 12)
    assert len(data) == 12
    assert data == [B,B,B,B,B,B,F,F,F,F,B,B]

def test_get_bitmap__recurring_availability_utc():
    u = mkuser()
    # availability in utc
    mkavail(u, datetime(2023, 1, 1, 0, 30), hrs(1), recur='forever')
    # viewed from london
    data = get_bitmap(u, datetime(2023, 1, 1), 'Europe/London', 12)
    assert len(data) == 12
    assert data == [B,B,F,F,F,F,B,B,B,B,B,B]
    # shifts during bst
    data = get_bitmap(u, datetime(2023, 4, 30), 'Europe/London', 12)
    assert len(data) == 12
    assert data == [B,B,B,B,B,B,F,F,F,F,B,B]
    # viewed from utc is at fixed time
    data = get_bitmap(u, datetime(2023, 1, 1), 'UTC', 12)
    assert len(data) == 12
    assert data == [B,B,F,F,F,F,B,B,B,B,B,B]
    data = get_bitmap(u, datetime(2023, 4, 30), 'UTC', 12)
    assert len(data) == 12
    assert data == [B,B,F,F,F,F,B,B,B,B,B,B]

def test_get_bitmap__overlapping_utc():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 1), mins(75), cost=0)
    mkavail(u, datetime(2023, 1, 1, 1, 45), mins(45), cost=1)
    mkavail(u, datetime(2023, 1, 1, 2), mins(45), cost=2)
    data = get_bitmap(u, datetime(2023, 1, 1, 1), 'UTC', 8)
    assert len(data) == 8
    assert data == [0,0,0,1,3,3,2,B]

@pytest.mark.parametrize('recur', [False, True])
def test_set_bitmap(recur):
    u = mkuser()
    start = datetime(2023, 1, 1)
    set_bitmap(u, start, 'UTC', [B,F,F,B,F], recur)
    db.session.commit()
    assert AEvent.query.count() == 2
    es = AEvent.query.order_by('start_at').all()
    assert es[0].start_at == start + mins(15)
    assert es[0].end_at == start + mins(45)
    assert es[0].recur_end_at == None if recur else start + mins(45)
    assert es[0].user == u
    assert es[0].tzname == 'UTC'
    assert es[1].start_at == start + hrs(1)
    assert es[1].end_at == start + hrs(1) + mins(15)
    assert es[1].recur_end_at == None if recur else start + hrs(1) + mins(15)
    assert es[1].user == u
    assert es[1].tzname == 'UTC'


def test_record_changes():
    u = mkuser()
    mkavail(u, datetime(2023, 1, 1, 0), hrs(1), cost=B)
    mkavail(u, datetime(2023, 1, 1, 1), hrs(1), cost=I)
    mkavail(u, datetime(2023, 1, 1, 2), hrs(1), cost=F)
    mkevent(u, [u.id], wstart=datetime(2023, 1, 1), wlength=days(7))
    record_changes(u, datetime(2023, 1, 1), 'UTC', [B,I,F,F,B,I,F,F,B,I,F,F], recur=False)
    db.session.commit()
    assert Change.query.count() == 4
    cs = Change.query.order_by('start_at').all()
    assert cs[0].start_at == datetime(2023, 1, 1, 0, 15)
    assert cs[0].end_at == datetime(2023, 1, 1, 1)
    assert not cs[0].conflict
    assert cs[1].start_at == datetime(2023, 1, 1, 1)
    assert cs[1].end_at == datetime(2023, 1, 1, 1, 15)
    assert cs[1].conflict
    assert cs[2].start_at == datetime(2023, 1, 1, 1, 30)
    assert cs[2].end_at == datetime(2023, 1, 1, 2)
    assert not cs[2].conflict
    assert cs[3].start_at == datetime(2023, 1, 1, 2)
    assert cs[3].end_at == datetime(2023, 1, 1, 2, 30)
    assert cs[3].conflict

def test_record_changes__recurring():
    u = mkuser()
    mkevent(u, [u.id], wstart=datetime(2023, 1, 1), wlength=days(14))
    record_changes(u, datetime(2023, 1, 1), 'UTC', [B,B,B,B,F,F,F,F,B,B], recur=True)
    db.session.commit()
    assert Change.query.count() == 2
    cs = Change.query.order_by('start_at').all()
    assert cs[0].start_at == datetime(2023, 1, 1, 1)
    assert cs[0].end_at == datetime(2023, 1, 1, 2)
    assert not cs[0].conflict
    assert cs[1].start_at == datetime(2023, 1, 8, 1)
    assert cs[1].end_at == datetime(2023, 1, 8, 2)
    assert not cs[1].conflict

def test_record_changes__recurring_past_last_meeting():
    u = mkuser()
    mkevent(u, [u.id], wstart=datetime(2023, 7, 1), wlength=days(7))
    record_changes(u, datetime(2023, 7, 8), 'UTC', [B,B,B,B,F,F,F,F,B,B], recur=True)
    db.session.commit()
    assert Change.query.count() == 0

def test_get_events_bitmap__trivial():
    u = mkuser()
    data = get_events_bitmap(u, datetime(2023, 1, 1), 'UTC', 12)
    assert data == [EventBitmap.FREE] * 12

def test_get_events_bitmap__utc():
    u = mkuser()
    mkfixedevent(u, datetime(2023, 1, 1, 0, 30), hrs(1))
    mkfixedevent(u, datetime(2023, 1, 1, 1, 55), mins(25))
    mkfixedevent(u, datetime(2023, 1, 1, 2, 45), mins(30))
    mkfixedevent(u, datetime(2023, 1, 1, 3), mins(30), '@kron free if needed')
    mkfixedevent(u, datetime(2023, 1, 1, 3, 45), hrs(1))
    data = get_events_bitmap(u, datetime(2023, 1, 1, 1), 'UTC', 12)
    F = EventBitmap.FREE
    I = EventBitmap.IFNEEDED
    B = EventBitmap.BUSY
    assert data == [B,B,F,B,B,B,F,B,B,I,F,B]


def test_get_meetings_bitmap__trivial():
    u = mkuser()
    data = get_meetings_bitmap(u, datetime(2023, 1, 1), 'UTC', 12)
    assert data == [EventBitmap.FREE] * 12

def test_get_meetings_bitmap__utc():
    c = mkuser()
    u = mkuser()
    e1 = mkevent(c, attendees=[u.id], length=hrs(1))
    e2 = mkevent(c, attendees=[c.id,u.id], length=mins(30))
    e3 = mkevent(c, attendees=[u.id], length=mins(15))
    e4 = mkevent(c, attendees=[u.id], length=hrs(1))
    schedule(e1, datetime(2023, 1, 1, 0, 30), [u.id])
    schedule(e2, datetime(2023, 1, 1, 2), [c.id]) # u doesn't make attendee list, so this shouldn't appear
    schedule(e3, datetime(2023, 1, 1, 3), [u.id])
    schedule(e4, datetime(2023, 1, 1, 3, 45), [u.id])
    data = get_meetings_bitmap(u, datetime(2023, 1, 1, 1), 'UTC', 12)
    F = EventBitmap.FREE
    B = EventBitmap.BUSY
    assert data == [B,B,F,F,F,F,F,F,B,F,F,B]


def test_add_core_availability__trivial():
    u = mkuser()
    add_core_availability(u, start_time=9, end_time=17, days=[])
    db.session.commit()
    assert AEvent.query.count() == 0

def test_add_core_availability():
    u = mkuser()
    add_core_availability(u, start_time=9, end_time=17, days=[0, 1, 2, 3, 4], utcnow=datetime(2023, 6, 7, 11))
    db.session.commit()
    es = AEvent.query.filter_by(user=u).order_by('start_at').all()
    assert len(es) == 5
    assert es[0].start_at == datetime(2023, 6, 7, 9)
    assert es[0].end_at == datetime(2023, 6, 7, 17)
    assert es[1].start_at == datetime(2023, 6, 8, 9)
    assert es[1].end_at == datetime(2023, 6, 8, 17)
    assert es[2].start_at == datetime(2023, 6, 9, 9)
    assert es[2].end_at == datetime(2023, 6, 9, 17)
    assert es[3].start_at == datetime(2023, 6, 12, 9)
    assert es[3].end_at == datetime(2023, 6, 12, 17)
    assert es[4].start_at == datetime(2023, 6, 13, 9)
    assert es[4].end_at == datetime(2023, 6, 13, 17)
    assert all(e.recur_end_at is None for e in es)
    assert all(e.tzname == u.tzname for e in es)
    assert all(e.cost == 0 for e in es)
