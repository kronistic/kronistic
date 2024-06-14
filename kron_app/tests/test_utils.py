from kron_app.utils import getstr, tzoptions, to_utc, from_utc, from_utc_to_s, advance_to_midnight, sanitize_url
from dateutil.tz import gettz, datetime_ambiguous, datetime_exists
from datetime import datetime, timedelta

def test_getstr():
    assert getstr(dict(), 'x') == ''
    assert getstr(dict(x=None), 'x') == ''
    assert getstr(dict(x=''), 'x') == ''
    assert getstr(dict(x='foo'), 'x') == 'foo'

def test_all_timezones_valid():
    for (tzname, _) in tzoptions():
        assert gettz(tzname)

def test_to_utc_gmt():
    tz = gettz('Europe/London')
    dt = datetime(2022, 3, 1, 9, 0)
    assert to_utc(dt, tz) == datetime(2022, 3, 1, 9, 0)

def test_to_utc_bst():
    tz = gettz('Europe/London')
    dt = datetime(2022, 6, 1, 9, 0)
    assert to_utc(dt, tz) == datetime(2022, 6, 1, 8, 0)

def test_to_utc_with_non_existent_dt_is_sane():
    tz = gettz('Europe/London')
    dt = datetime(2022, 3, 27, 1, 30, tzinfo=tz)
    assert not datetime_exists(dt)
    dtutc = to_utc(dt.replace(tzinfo=None), tz)
    assert dtutc.replace(hour=0, minute=0) == datetime(2022, 3, 27)

def test_to_utc_with_ambiguous_dt_is_sane():
    tz = gettz('Europe/London')
    dt = datetime(2022, 10, 30, 1, 30, tzinfo=tz)
    assert datetime_ambiguous(dt)
    dtutc = to_utc(dt.replace(tzinfo=None), tz)
    assert dtutc.replace(hour=0, minute=0) == datetime(2022, 10, 30)

def test_from_utc_gmt():
    utcnow = datetime(2022, 2, 1)
    tz = gettz('Europe/London')
    dt = datetime(2022, 3, 1, 9, 0)
    assert from_utc(dt, tz) == datetime(2022, 3, 1, 9, 0)
    assert from_utc_to_s(dt, tz, utcnow=utcnow) == 'Tue, March 1, at 9:00 GMT'
    assert from_utc_to_s(dt, tz, utcnow=utcnow-timedelta(days=300)) == 'Tue, March 1, 2022, at 9:00 GMT'
    assert from_utc_to_s(dt, tz, short=True, utcnow=utcnow) == '2022-03-01 09:00 GMT'

def test_from_utc_bst():
    utcnow = datetime(2022, 5, 1)
    tz = gettz('Europe/London')
    dt = datetime(2022, 6, 1, 8, 0)
    assert from_utc(dt, tz) == datetime(2022, 6, 1, 9, 0)
    assert from_utc_to_s(dt, tz, utcnow=utcnow) == 'Wed, June 1, at 9:00 BST'
    assert from_utc_to_s(dt, tz, utcnow=utcnow-timedelta(days=300)) == 'Wed, June 1, 2022, at 9:00 BST'
    assert from_utc_to_s(dt, tz, short=True, utcnow=utcnow) == '2022-06-01 09:00 BST'

def test_advance_to_midnight():
    assert advance_to_midnight(datetime(2022, 8, 2, 14, 20)) == datetime(2022, 8, 3)
    assert advance_to_midnight(datetime(2022, 8, 3)) == datetime(2022, 8, 3)
    assert advance_to_midnight(datetime(2022, 8, 3, 0, 0, 1)) == datetime(2022, 8, 4)
    assert advance_to_midnight(datetime(2022, 8, 3, 0, 0, 0, 1)) == datetime(2022, 8, 4)

def test_sanitize_url():
    assert sanitize_url('/meetings', 'https', 'kronistic.com') == 'https://kronistic.com/meetings'
    assert sanitize_url('/meeting/1', 'https', 'kronistic.com') == 'https://kronistic.com/meeting/1'
    assert sanitize_url('example.com', 'https', 'kronistic.com').startswith('https://kronistic.com')
    assert sanitize_url('https://example.com', 'https', 'kronistic.com').startswith('https://kronistic.com')
    assert sanitize_url('http://example.com/path', 'https', 'kronistic.com').startswith('https://kronistic.com')
