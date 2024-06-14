import pytest
from kron_app.templates.helpers import fmt_available_time, tosentence

@pytest.mark.parametrize('kwargs, expected', [
    (dict(days=[5,6], start_time=9, end_time=17),
     '9:00 - 17:00 on Saturdays and Sundays'),
    (dict(days=[2,1,0], start_time=8, end_time=18),
     '8:00 - 18:00 on Mondays, Tuesdays and Wednesdays'),
    (dict(days=[4,3,2,1,0], start_time=9, end_time=17),
     '9:00 - 17:00 on weekdays'),
    (dict(days=[0,1,2,3,4,5,6], start_time=9, end_time=17),
     '9:00 - 17:00 on any day'),
    (dict(days=[0,1,2,3,4,5], start_time=9, end_time=17),
     '9:00 - 17:00 on any day except Sundays'),
])
def test_fmt_available_time(kwargs, expected):
    assert fmt_available_time(**kwargs) == expected

@pytest.mark.parametrize('items, expected', [
    (['foo'], 'foo'),
    (['foo', 'bar', 'baz'], 'foo, bar and baz'),
    ((s for s in ['foo', 'bar', 'baz']), 'foo, bar and baz')
])
def test_tosentence(items, expected):
    assert tosentence(items) == expected
