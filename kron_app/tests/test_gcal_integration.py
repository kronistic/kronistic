import pytest
from datetime import datetime, timedelta
from kron_app import db
from kron_app.tests.helpers import mkuser, mkevent, schedule, unschedule
from kron_app.gcal_integration import is_free, get_start_end, get_kron_duty_and_costs, gcal_update_api_quotas, gcal_event_queue_for

def test_creator_no_attendees():
    item = {'created': '2022-04-06T13:20:06.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'dateTime': '2022-04-07T15:45:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298502413348000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NTliZHU2cTVrczRsMTRxdGxrZG5xaGw2NnEgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '59bdu6q5ks4l14qtlkdnqhl66q@google.com',
            'id': '59bdu6q5ks4l14qtlkdnqhl66q',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T09:15:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:20:06.674Z'}
    assert not is_free(item)

def test_creator_no_attendees_marked_free():
    item = {'created': '2022-04-06T14:49:19.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'dateTime': '2022-04-07T19:15:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298513140642000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=N3MwZXYxMTY5bHA1azdmbjFmbjJzYjVzdTIgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '7s0ev1169lp5k7fn1fn2sb5su2@google.com',
            'id': '7s0ev1169lp5k7fn1fn2sb5su2',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T08:15:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'transparency': 'transparent',
            'updated': '2022-04-06T14:49:30.321Z'}
    assert is_free(item)

def test_creator_with_attendees_accepted():
    item = {'attendees': [{'email': 'noah@kronistic.com',
                           'responseStatus': 'needsAction'},
                          {'email': 'paul@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted',
                           'self': True}],
            'created': '2022-04-06T13:20:06.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'dateTime': '2022-04-07T15:45:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298503171030000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NTliZHU2cTVrczRsMTRxdGxrZG5xaGw2NnEgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '59bdu6q5ks4l14qtlkdnqhl66q@google.com',
            'id': '59bdu6q5ks4l14qtlkdnqhl66q',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T09:15:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:26:25.515Z'}
    assert not is_free(item)

def test_creator_with_attendees_accepted_marked_free():
    item = {'attendees': [{'email': 'noah@kronistic.com',
                           'responseStatus': 'needsAction'},
                          {'email': 'paul@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted',
                           'self': True}],
            'created': '2022-04-06T15:01:59.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'dateTime': '2022-04-07T20:45:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298514667814000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=MzEwZTZiM2pnaGxpYmdidTY2b2xwMmxmamwgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '310e6b3jghlibgbu66olp2lfjl@google.com',
            'id': '310e6b3jghlibgbu66olp2lfjl',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T09:45:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'transparency': 'transparent',
            'updated': '2022-04-06T15:02:13.907Z'}
    assert is_free(item)

def test_creator_with_attendees_declined():
    item = {'attendees': [{'email': 'noah@kronistic.com',
                           'responseStatus': 'needsAction'},
                          {'email': 'paul@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'declined',
                           'self': True}],
            'created': '2022-04-06T13:20:06.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'dateTime': '2022-04-07T15:45:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298503413752000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NTliZHU2cTVrczRsMTRxdGxrZG5xaGw2NnEgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '59bdu6q5ks4l14qtlkdnqhl66q@google.com',
            'id': '59bdu6q5ks4l14qtlkdnqhl66q',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T09:15:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:28:26.876Z'}
    assert is_free(item)

def test_invited_not_responded():
    item = {'attendees': [{'email': 'paul@kronistic.com',
                           'responseStatus': 'needsAction',
                           'self': True},
                          {'email': 'noah@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted'}],
            'created': '2022-04-06T13:40:42.000Z',
            'creator': {'email': 'noah@kronistic.com'},
            'end': {'dateTime': '2022-04-07T16:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298504886352000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NWo0MnIxdTVlam02M2RlYjllaGdjN3J0ajggcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '5j42r1u5ejm63deb9ehgc7rtj8@google.com',
            'id': '5j42r1u5ejm63deb9ehgc7rtj8',
            'kind': 'calendar#event',
            'organizer': {'email': 'noah@kronistic.com'},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T15:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:40:43.176Z'}
    assert is_free(item)

def test_invited_declined():
    item = {'attendees': [{'email': 'paul@kronistic.com',
                           'responseStatus': 'declined',
                           'self': True},
                          {'email': 'noah@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted'}],
            'created': '2022-04-06T13:40:42.000Z',
            'creator': {'email': 'noah@kronistic.com'},
            'end': {'dateTime': '2022-04-07T16:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298505282798000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NWo0MnIxdTVlam02M2RlYjllaGdjN3J0ajggcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '5j42r1u5ejm63deb9ehgc7rtj8@google.com',
            'id': '5j42r1u5ejm63deb9ehgc7rtj8',
            'kind': 'calendar#event',
            'organizer': {'email': 'noah@kronistic.com'},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T15:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:44:01.399Z'}
    assert is_free(item)

def test_invited_tentative():
    item = {'attendees': [{'email': 'paul@kronistic.com',
                           'responseStatus': 'tentative',
                           'self': True},
                          {'email': 'noah@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted'}],
            'created': '2022-04-06T13:40:42.000Z',
            'creator': {'email': 'noah@kronistic.com'},
            'end': {'dateTime': '2022-04-07T16:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298505282798000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NWo0MnIxdTVlam02M2RlYjllaGdjN3J0ajggcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '5j42r1u5ejm63deb9ehgc7rtj8@google.com',
            'id': '5j42r1u5ejm63deb9ehgc7rtj8',
            'kind': 'calendar#event',
            'organizer': {'email': 'noah@kronistic.com'},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T15:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:44:01.399Z'}
    assert is_free(item)

def test_invited_accepted():
    item = {'attendees': [{'email': 'paul@kronistic.com',
                           'responseStatus': 'accepted',
                           'self': True},
                          {'email': 'noah@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted'}],
            'created': '2022-04-06T13:40:42.000Z',
            'creator': {'email': 'noah@kronistic.com'},
            'end': {'dateTime': '2022-04-07T16:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298505427758000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NWo0MnIxdTVlam02M2RlYjllaGdjN3J0ajggcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '5j42r1u5ejm63deb9ehgc7rtj8@google.com',
            'id': '5j42r1u5ejm63deb9ehgc7rtj8',
            'kind': 'calendar#event',
            'organizer': {'email': 'noah@kronistic.com'},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T15:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:45:13.879Z'}
    assert not is_free(item)

def test_invited_accepted_marked_free():
    item = {'attendees': [{'email': 'paul@kronistic.com',
                           'responseStatus': 'accepted',
                           'self': True},
                          {'email': 'noah@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted'}],
            'created': '2022-04-06T14:57:44.000Z',
            'creator': {'email': 'noah@kronistic.com'},
            'end': {'dateTime': '2022-04-07T17:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298514331964000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=MDFiZTZ2azdjNTk4b3NiczQ5OWZhc2t1cXMgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '01be6vk7c598osbs499faskuqs@google.com',
            'id': '01be6vk7c598osbs499faskuqs',
            'kind': 'calendar#event',
            'organizer': {'email': 'noah@kronistic.com'},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T16:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'transparency': 'transparent',
            'updated': '2022-04-06T14:59:25.982Z'}
    assert is_free(item)

def test_invited_multiple_self():
    # We've seen an example where the gcal response includes two
    # attendees with `self=True` set. In that case, both selves had
    # the same `email` and `responseStatus`. We don't know that that
    # will always be the case, so we'll count as busy any item where
    # some attendee with `self=True` has `responseStatus=accepted`.
    item = {'attendees': [{'email': 'paul1@kronistic.com',
                           'responseStatus': 'declined',
                           'self': True},
                          {'email': 'paul2@kronistic.com',
                           'responseStatus': 'accepted',
                           'self': True},
                          {'email': 'noah@kronistic.com',
                           'organizer': True,
                           'responseStatus': 'accepted'}],
            'created': '2022-04-06T13:40:42.000Z',
            'creator': {'email': 'noah@kronistic.com'},
            'end': {'dateTime': '2022-04-07T16:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3298505427758000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NWo0MnIxdTVlam02M2RlYjllaGdjN3J0ajggcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '5j42r1u5ejm63deb9ehgc7rtj8@google.com',
            'id': '5j42r1u5ejm63deb9ehgc7rtj8',
            'kind': 'calendar#event',
            'organizer': {'email': 'noah@kronistic.com'},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-07T15:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'updated': '2022-04-06T13:45:13.879Z'}
    assert not is_free(item)

def test_get_start_end_event_with_times():
    item = {'created': '2022-04-25T10:20:46.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'dateTime': '2022-04-26T11:00:00+01:00',
                    'timeZone': 'Europe/London'},
            'etag': '"3301764093988000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=NDlsNzJoczhncGcwcWtqbnNycGFkc3Z2a3Ygcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '49l72hs8gpg0qkjnsrpadsvvkv@google.com',
            'id': '49l72hs8gpg0qkjnsrpadsvvkv',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': True},
            'sequence': 0,
            'start': {'dateTime': '2022-04-26T10:00:00+01:00',
                      'timeZone': 'Europe/London'},
            'status': 'confirmed',
            'summary': 'timed event',
            'updated': '2022-04-25T10:20:46.994Z'}
    start, end, allday = get_start_end(item)
    assert start == datetime(2022, 4, 26, 9, 0)
    assert end == datetime(2022, 4, 26, 10, 0)
    assert not allday

def test_get_start_end_all_day_event():
    item = {'created': '2022-04-25T12:51:53.000Z',
            'creator': {'email': 'paul@kronistic.com', 'self': True},
            'end': {'date': '2022-04-29'},
            'etag': '"3301782227524000"',
            'eventType': 'default',
            'htmlLink': 'https://www.google.com/calendar/event?eid=M2Ewbjh0ZWJ0bm9lN2tkY2NhYTZubDc1dWMgcm9zaGFtYm8uYm90QGdvb2dsZW1haWwuY29t',
            'iCalUID': '3a0n8tebtnoe7kdccaa6nl75uc@google.com',
            'id': '3a0n8tebtnoe7kdccaa6nl75uc',
            'kind': 'calendar#event',
            'organizer': {'email': 'paul@kronistic.com', 'self': True},
            'reminders': {'useDefault': False},
            'sequence': 0,
            'start': {'date': '2022-04-27'},
            'status': 'confirmed',
            'summary': 'all day 2',
            'transparency': 'transparent',
            'updated': '2022-04-25T12:51:53.762Z'}
    start, end, allday = get_start_end(item)
    assert start == datetime(2022, 4, 27)
    assert end == datetime(2022, 4, 29)
    assert allday

@pytest.mark.parametrize('item, expected', [
    (dict(), (False, None)),
    (dict(summary='kron'), (False, None)),
    (dict(summary='@kron'), (True, {'everyone':0})),
    (dict(summary='kron if needed'), (False, None)),
    (dict(summary='@kron if needed'), (True, {'everyone':1})),
    (dict(description='kron'), (False, None)),
    (dict(description='@kron'), (True, {'everyone':0})),
    (dict(description='@kron if needed'), (True, {'everyone':1})),
    (dict(summary='@kron', description='@kron if needed'), (True, {'everyone':0})),
])
def test_get_kron_duty_and_costs(item, expected):
  assert get_kron_duty_and_costs(item) == expected

def test_gcal_quota(testdb):
    u1 = mkuser('user@gmail.com')
    u2 = mkuser('user@googlemail.com')
    u3 = mkuser('user@example.com')
    assert u1.gcal_quota == 200
    assert u1.gcal_quota_max == 200
    assert u1.gcal_quota_period == timedelta(minutes=180)
    assert u1.gcal_is_free_account
    assert u2.gcal_quota == 200
    assert u2.gcal_quota_max == 200
    assert u2.gcal_quota_period == timedelta(minutes=180)
    assert u2.gcal_is_free_account
    assert u3.gcal_quota == 1000
    assert u3.gcal_quota_max == 1000
    assert u3.gcal_quota_period == timedelta(minutes=15)
    assert not u3.gcal_is_free_account

def test_gcal_update_api_quotas(testdb):
    utcnow = datetime.utcnow()
    k = mkuser('k')
    p = mkuser('p')
    n = mkuser('n')
    e = mkuser('e')
    for u in [k,p,n,e]:
        u.gcal_quota_period = timedelta(hours=2)
    db.session.commit()
    # multiple periods have elapsed, quota should increase
    k.gcal_quota = 0
    k.gcal_quota_updated_at = utcnow - timedelta(hours=5)
    # multiple periods have elapsed, quota should increase
    p.gcal_quota = 1
    p.gcal_quota_updated_at = utcnow - timedelta(hours=5)
    # multiple periods have elapsed, but already at max, so no change
    n.gcal_quota = n.gcal_quota_max
    n.gcal_quota_updated_at = utcnow - timedelta(hours=5)
    # period hasn't elapsed, no change
    e.gcal_quota = 7
    e.gcal_quota_updated_at = utcnow - timedelta(hours=1.5)
    db.session.commit()
    todrain = list(gcal_update_api_quotas(utcnow).keys())
    db.session.rollback()
    assert todrain == [k.id]
    assert k.gcal_quota == 2
    assert k.gcal_quota_updated_at == utcnow - timedelta(hours=1)
    assert p.gcal_quota == 3
    assert p.gcal_quota_updated_at == utcnow - timedelta(hours=1)
    assert n.gcal_quota == n.gcal_quota_max
    assert n.gcal_quota_updated_at == utcnow - timedelta(hours=1)
    assert e.gcal_quota == 7
    assert e.gcal_quota_updated_at == utcnow - timedelta(hours=1.5)

def test_gcal_event_queue_for(testdb):
    u = mkuser('u')
    e1 = mkevent(u, attendees=[u.id])
    schedule(e1, e1.window_start+timedelta(hours=1), [u.id])
    e2 = mkevent(u, attendees=[u.id])
    schedule(e2, e2.window_start, [u.id])
    e3 = mkevent(u, attendees=[u.id])
    unschedule(e3)
    assert gcal_event_queue_for(u.id) == [e2,e1]
