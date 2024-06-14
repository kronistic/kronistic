import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from collections import namedtuple
from functools import partial
from kron_app import db
from kron_app.tests.helpers import mkuser, mkevent, schedule, unschedule, mkcal, mkfixedevent as mkfixed, mins
from kron_app.utils import uid
from kron_app.models import Event, FixedEvent, Change, Email, GcalResponseState, Attendance
from kron_app.gcal_api import GCAL_EVENT_UID_PREFIX
from kron_app.gcal_integration import gcal_sync_full, gcal_sync_incremental, IncSyncResult, gcal_sync_event_2

def mkitem(**kwargs):
    # Map `uid` arg to `id`.
    extra = dict(('id' if k == 'uid' else k,v) for k,v in kwargs.items())
    return dict({'id': str(uuid4()),
                 'status': 'confirmed',
                 'start': {'dateTime': '2022-04-07T09:15:00+01:00'},
                 'end': {'dateTime': '2022-04-07T15:45:00+01:00'}},
                **extra)

def mkbusy(**kwargs):
    return mkitem(status='confirmed', **kwargs)

def mkfree(**kwargs):
    return mkitem(transparency='transparent', **kwargs)

NEXT = 'next_sync_token'
CONT = (None, None)
DONE = ('ok', NEXT)

# This simulates the gcal api by wrapping raw api calendar entries in
# the same data structure returned by `gcal_list_entries_generator`.
def sim_api(*pages):
    n = len(pages)
    results = [CONT]*(n-1) + [DONE]
    return list(zip(pages, results))

def fixed(calendar):
    return FixedEvent.query.filter_by(calendar=calendar)

def change():
    return Change.query

# =INCREMENTAL=SYNC=============================================================

def test_inc_sync_full_sync_required_no_sync_token(testdb):
    u = mkuser()
    c = u.primary_calendar
    c.gcal_sync_token = None
    db.session.commit()
    result = gcal_sync_incremental(c, sim_api([]))
    db.session.rollback()
    assert result == IncSyncResult.full_sync_required

def test_inc_sync_full_sync_required(testdb):
    u = mkuser()
    c = u.primary_calendar
    api_calls = [([], ('full_sync_required', None))]
    result = gcal_sync_incremental(c, api_calls)
    db.session.rollback()
    assert result == IncSyncResult.full_sync_required

def test_inc_sync_nothing_to_do(testdb):
    u = mkuser()
    c = u.primary_calendar
    result = gcal_sync_incremental(c, sim_api([]))
    db.session.rollback()
    assert result == IncSyncResult.no_changes_made
    assert c.gcal_sync_token == NEXT
    assert FixedEvent.query.count() == 0
    assert change().count() == 0

def test_inc_sync_add_event(testdb):
    u = mkuser()
    c = u.primary_calendar
    i, j = mkbusy(), mkbusy()
    result = gcal_sync_incremental(c, sim_api([i], [j]))
    db.session.rollback()
    assert result == IncSyncResult.changes_made
    assert c.gcal_sync_token == NEXT
    assert fixed(c).count() == 2
    fs = fixed(c).all()
    assert all(f.dirty for f in fs)
    assert set(f.uid for f in fs) == set(item['id'] for item in [i,j])
    assert change().count() == 0

def test_inc_sync_update_existing_event(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c)
    assert not f.dirty
    assert fixed(c).count() == 1
    assert change().count() == 0
    i = mkbusy(uid=f.uid)
    result = gcal_sync_incremental(c, sim_api([i]))
    db.session.rollback()
    assert result == IncSyncResult.changes_made
    assert fixed(c).count() == 1
    assert fixed(c).first().dirty
    assert change().count() == 1

def test_inc_sync_remove_events(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c)
    assert fixed(c).count() == 1
    assert change().count() == 0
    i = mkitem(uid=f.uid, status='cancelled')
    result = gcal_sync_incremental(c, sim_api([i]))
    db.session.rollback()
    assert result == IncSyncResult.changes_made
    assert fixed(c).count() == 0
    assert change().count() == 1

def test_inc_sync_free_time(testdb):
    u = mkuser()
    c = u.primary_calendar
    i = mkbusy()
    f = mkfixed(c)
    assert fixed(c).count() == 1
    assert change().count() == 0
    i = mkfree(uid=f.uid) # f marked as free
    j = mkfree() # new free event
    result = gcal_sync_incremental(c, sim_api([i,j]))
    db.session.rollback()
    assert fixed(c).count() == 0
    assert result == IncSyncResult.changes_made
    assert change().count() == 1

def test_inc_sync_kron_events(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c)
    assert fixed(c).count() == 1
    i = mkfree(summary='@kron',uid=f.uid)
    j = mkbusy(summary='@kron')
    gcal_sync_incremental(c, sim_api([i,j]))
    db.session.rollback()
    assert fixed(c).count() == 2
    assert all(f.kron_duty for f in fixed(c).all())
    assert all(type(f.costs) == dict for f in fixed(c).all())

def test_inc_sync_does_not_add_float_as_fixed(testdb):
    u = mkuser()
    c = u.primary_calendar
    i = mkbusy(uid=GCAL_EVENT_UID_PREFIX+uid())
    result = gcal_sync_incremental(c, sim_api([i]))
    db.session.rollback()
    assert FixedEvent.query.count() == 0
    assert result == IncSyncResult.no_changes_made

def test_inc_sync_recurring_event_fix_up(testdb):
    u = mkuser()
    c = u.primary_calendar
    c2 = mkcal(u)
    i = mkbusy() # Hypothetical non-recurring event ...
    gcal_sync_incremental(c, sim_api([i]))
    db.session.rollback()
    assert fixed(c).count() == 1
    assert change().count() == 0
    j = mkbusy() # ... made to recur.
    j['recurringEventId'] = i['id']
    # We don't get a 'cancelled' entry for i.
    result = gcal_sync_incremental(c2, sim_api([j]))
    db.session.rollback()
    assert result == IncSyncResult.changes_made
    assert fixed(c).count() == 0
    assert fixed(c2).count() == 1
    f = fixed(c2).first()
    assert f.uid == j['id']
    assert f.dirty
    assert change().count() == 1

# =FULL=SYNC====================================================================

def test_full_sync_imports_busy_entries(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c) # Existing fixed event will be removed
    assert FixedEvent.query.count() == 1
    i = mkbusy() # Added
    j = mkbusy() # Added
    k = mkfree() # Not added, since free time
    gcal_sync_full(c, sim_api([i,j,k]))
    db.session.rollback()
    assert c.gcal_sync_token == NEXT
    assert FixedEvent.query.count() == 2
    assert set(f.uid for f in FixedEvent.query.all()) == set(item['id'] for item in [i,j])

def test_full_sync_kron_events(testdb):
    u = mkuser()
    c = u.primary_calendar
    assert fixed(c).count() == 0
    i = mkfree(summary='@kron')
    j = mkbusy(summary='@kron')
    gcal_sync_full(c, sim_api([i,j]))
    db.session.rollback()
    assert fixed(c).count() == 2
    assert all(f.kron_duty for f in fixed(c).all())

def test_full_sync_does_not_add_float_as_fixed(testdb):
    u = mkuser()
    c = u.primary_calendar
    i = mkbusy(uid=GCAL_EVENT_UID_PREFIX+uid())
    gcal_sync_full(c, sim_api([i]))
    db.session.rollback()
    assert FixedEvent.query.count() == 0

def test_full_sync_api_error_does_not_clobber_fixed_events(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c)
    assert FixedEvent.query.count() == 1
    def api_calls():
        raise Exception('unhandled api exception')
    try:
        gcal_sync_full(c, api_calls)
    except:
        pass
    assert FixedEvent.query.count() == 1

def test_full_sync_new_entry(testdb):
    u = mkuser()
    c = u.primary_calendar
    i = mkbusy()
    assert fixed(c).count() == 0
    assert change().count() == 0
    gcal_sync_full(c, sim_api([i]))
    db.session.rollback()
    assert fixed(c).count() == 1
    f = fixed(c).first()
    assert f.dirty
    assert f.uid == i['id']
    assert change().count() == 0

def test_full_sync_unchanged_entry(testdb):
    u = mkuser()
    c = u.primary_calendar
    i = mkbusy()
    assert fixed(c).count() == 0
    assert change().count() == 0
    gcal_sync_full(c, sim_api([i]))
    db.session.rollback()
    assert fixed(c).count() == 1
    f = fixed(c).first()
    assert f.dirty
    f.dirty = False
    db.session.commit()
    gcal_sync_full(c, sim_api([i]))
    db.session.rollback()
    assert fixed(c).count() == 1
    f = fixed(c).first()
    assert not f.dirty
    assert change().count() == 0

def test_full_sync_update_entry(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c)
    uid = f.uid
    i = mkbusy(uid=uid)
    assert fixed(c).count() == 1
    assert change().count() == 0
    f = fixed(c).first()
    assert not f.dirty
    gcal_sync_full(c, sim_api([i]))
    db.session.rollback()
    assert fixed(c).count() == 1
    f = fixed(c).first()
    assert f.uid == uid
    assert f.dirty
    assert change().count() == 1

def test_full_sync_delete_entry(testdb):
    u = mkuser()
    c = u.primary_calendar
    f = mkfixed(c)
    assert fixed(c).count() == 1
    assert change().count() == 0
    f = fixed(c).first()
    assert not f.dirty
    gcal_sync_full(c, sim_api([]))
    db.session.rollback()
    assert fixed(c).count() == 0
    assert change().count() == 1

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_motion_events(testdb, gcal_sync):
    u = mkuser()
    c = u.primary_calendar
    i = mkitem()
    # This snippet is taken from a motion event pulled from the gcal api.
    # {'extendedProperties': {'shared': {'motionUserId': 'xxxx', 'motionTaskId': 'xxxx'}}}
    i['extendedProperties'] = dict(shared=dict(motionUserId='xxxx', motionTaskId='xxxx'))
    assert fixed(c).count() == 0
    gcal_sync(c, sim_api([i]))
    db.session.rollback()
    assert fixed(c).count() == 1
    f = fixed(c).first()
    assert f.kron_duty
    assert f.costs == dict(everyone=1)

# Tests of event pull sync (inc & full)

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_handles_duplicate_items(testdb, gcal_sync):
    # During local testing I encountered the api returning (identical)
    # duplicate items (on the same api page) for a single event.
    # Post-switching to bulk fetching fixed events, this will trigger
    # an integrity error without handling.
    u = mkuser()
    c = u.primary_calendar
    i = mkitem()
    gcal_sync(c, sim_api([i,i],[i]))
    db.session.rollback
    assert fixed(c).count() == 1

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_handles_year_0(testdb, gcal_sync):
    u = mkuser()
    c = u.primary_calendar
    # timed event, as seen in production (#767)
    i = mkitem(start=dict(dateTime='0000-01-01T00:00:00'),
               end=dict(dateTime='0000-01-01T01:00:00'))
    # all-day event
    j = mkitem(start=dict(date='0000-01-01'),
               end=dict(date='0000-01-02'))
    gcal_sync(c, sim_api([i,j]))
    db.session.rollback()
    assert fixed(c).count() == 2

# Test populating contacts

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_preserves_existing_contacts(testdb, gcal_sync):
    n = mkuser('noah@kronistic.com')
    p = mkuser('paul@kronistic.com')
    n.contacts.append(p)
    p.contacts.append(n)
    db.session.commit()
    i = mkitem(attendees=[])
    gcal_sync(n.primary_calendar, sim_api([i]))
    db.session.rollback()
    assert n.contacts == [p]
    assert p.contacts == [n]

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_skips_known_contacts(testdb, gcal_sync):
    n = mkuser('noah@kronistic.com')
    p = mkuser('paul@kronistic.com')
    n.contacts.append(p)
    p.contacts.append(n)
    db.session.commit()
    i = mkitem(attendees=[{'email': p.email}])
    gcal_sync(n.primary_calendar, sim_api([i]))
    db.session.rollback()
    assert n.contacts == [p]
    assert p.contacts == [n]

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_adds_contacts(testdb, gcal_sync):
    n = mkuser('noah@kronistic.com')
    p = mkuser('paul@kronistic.com')
    e = mkuser('emily@kronistic.com')
    o = mkuser('other@kronistic.com')
    i = mkitem(attendees = [{'email': n.email}, {'email': p.email.upper()}]) # Self present as attendee; attendee email case mismatch
    j = mkitem(attendees = [{'email': e.email}, {'email': 'other@example.com'}]) # Self not present
    k = mkitem(attendees = [{'email': 'other@example.com'}])
    assert all(u.contacts == [] for u in [n,p,e,o])
    gcal_sync(n.primary_calendar, sim_api([i,j,k]))
    db.session.rollback()
    assert set(n.contacts) == {p,e}
    assert set(p.contacts) == {n}
    assert set(e.contacts) == {n}
    assert set(o.contacts) == set()

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_adds_contacts_all_pairs(testdb, gcal_sync):
    n = mkuser('noah@kronistic.com')
    p = mkuser('paul@kronistic.com')
    e = mkuser('emily@kronistic.com')
    o = mkuser('other@kronistic.com')
    i = mkitem(attendees = [{'email': p.email}, {'email': e.email}, {'email': 'other@example.com'}])
    assert all(u.contacts == [] for u in [n,p,e,])
    gcal_sync(n.primary_calendar, sim_api([i]))
    db.session.rollback()
    assert set(n.contacts) == {p,e}
    assert set(p.contacts) == {n,e}
    assert set(e.contacts) == {n,p}
    assert set(o.contacts) == set()

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_adds_known_alias_as_contact(testdb, gcal_sync):
    p = mkuser('paul@kronistic.com')
    n = mkuser('noah@kronistic.com', alias='noah@stanford.edu')
    i = mkitem(attendees = [{'email': p.email}, {'email': n.aliases[0]}])
    assert all(u.contacts == [] for u in [n,p])
    gcal_sync(p.primary_calendar, sim_api([i]))
    db.session.rollback()
    assert set(n.contacts) == {p}
    assert set(p.contacts) == {n}

@pytest.mark.parametrize('gcal_sync', [gcal_sync_incremental, gcal_sync_full])
def test_sync_handles_entries_with_own_alias(testdb, gcal_sync):
    p = mkuser('paul@kronistic.com', alias='paul@example.com')
    i = mkitem(attendees = [{'email': p.email}, {'email': p.aliases[0]}])
    assert p.contacts == []
    gcal_sync(p.primary_calendar, sim_api([i]))
    db.session.rollback()
    assert p.contacts == []

# =PUSH=SYNC====================================================================

# `Api` might be better as a coroutine / producer / consumer jobbie.

# TODO: this is at the level of the methods in gcal_api, and not e.g.
# the http methods on the oauth session obj. Is that the best choice?

ApiGet    = namedtuple('ApiGet',    'method')
ApiCreate = namedtuple('ApiCreate', 'method params')
ApiUpdate = namedtuple('ApiUpdate', 'method entry params')
ApiDelete = namedtuple('ApiDelete', 'method')
ApiExists = namedtuple('ApiExists', 'method')
api_get    = partial(ApiGet,    'GET')
api_create = partial(ApiCreate, 'CREATE')
api_update = partial(ApiUpdate, 'UPDATE')
api_delete = partial(ApiDelete, 'DELETE')
api_exists = partial(ApiExists, 'EXISTS')

class Api:
    def __init__(self, get=[], exists=[]):
        self.ops = []
        self._get = get[::-1] # reversed, for convenient pop
        self._exists = exists[::-1]
    def get(self, *args, **kwargs):
        self.ops.append(api_get())
        # minimal response to allow gcal_sync_event to execute.
        return self._get.pop() if len(self._get) > 0 else dict(attendees=[])
    def create(self, google, gcal_id, entry, params={}):
        self.ops.append(api_create(params))
        uid = entry['id'] # pass through uid
        return uid
    def update(self, google, gcal_id, entry, uid, params={}, patch=False):
        self.ops.append(api_update(entry, params))
    def delete(self, *args, **kwargs):
        self.ops.append(api_delete())
    def exists(self, *args, **kwargs):
        return self._exists.pop() if len(self._exists) > 0 else False

def sim_push_sync(e):
    gcal_sync_event(e.id, Api())

# Maybe we should simulate the api, rather that just intercept & log method calls.
#
# This could also return `api_call` lists to be passed to inc/full sync.
#
# The question of whether to simulate at this level, or at the level
# of http endpoints remains.

# class Api2:
#     def __init__(self, items=[]): # could take calendar id, and check callers do as expected with gcal_id etc.
#         self.items = items # assumes uids are unique
#     def get(self, google, calendar, uid):
#         return [_ for i in self.items if i['id'] == uid][0] # will error if doesn't exist
#     def create(self, google, gcal_id, entry, params={}):
#         uid = entry['id']
#         assert len([_ for i in self.items if i['id'] == uid]) == 0
#         self.items.append(entry)
#         return uid
#     def update(self, google, calendar, entry, uid, params={}, patch=False):
#         assert patch
#         item = [_ for i in self.items if i['id'] == uid][0]
#         for k,v in entry:
#             item[k] = v
        # set attendees' responseStatus

def gcal_counts(obj):
    assert type(obj) in (Event, Attendance)
    return (obj.gcal_create_count,
            obj.gcal_update_count,
            obj.gcal_delete_count)
def sim_push_sync_2(a):
    gcal_sync_event_2(a.id, Api())

def the_attendance(e):
    assert len(e.attendances) == 1
    return e.attendances[0]

def test_gcal_push_sync_2__new_entry(testdb):
    u = mkuser('u')
    v = mkuser('v')
    e1 = mkevent(u, [v.id])
    schedule(e1, e1.window_start, [v.id])
    a = the_attendance(e1)
    assert gcal_counts(a) == (0,0,0)
    assert a.gcal_uid is None
    api = Api()
    gcal_sync_event_2(a.id, api)
    db.session.rollback()
    assert len(api.ops) == 1
    assert api.ops[0].method == 'CREATE'
    assert type(a.gcal_uid) == str
    assert type(a.gcal_hash) == str
    assert a.gcal_push_id and a.gcal_push_id == v.gcal_push_id
    assert gcal_counts(a) == (1,0,0)

def test_gcal_push_sync_2__new_entry_skipped_when_insufficient_quota(testdb):
    u = mkuser('u')
    v = mkuser('v')
    v.gcal_quota = 0 # TODO: push to helper?
    db.session.commit()
    e1 = mkevent(u, [v.id])
    schedule(e1, e1.window_start, [v.id])
    a = the_attendance(e1)
    api = Api()
    gcal_sync_event_2(a.id, api)
    db.session.rollback()
    assert len(api.ops) == 0
    assert a.gcal_uid is None
    assert gcal_counts(a) == (0,0,0)

def test_gcal_push_sync_2__update_entry(testdb):
    u = mkuser('u')
    e1 = mkevent(u, [u.id])
    schedule(e1, e1.window_start, [u.id])
    a = the_attendance(e1)
    sim_push_sync_2(a)
    assert gcal_counts(a) == (1,0,0)
    old_gcal_uid = a.gcal_uid
    old_gcal_hash = a.gcal_hash
    # modify meeting such that calendar entry changes
    e1.title += '!'
    db.session.commit()
    # calendar entry remains accepted
    api = Api(get=[dict(attendees=[dict(email=u.email, responseStatus='accepted')])])
    gcal_sync_event_2(a.id, api)
    db.session.rollback()
    assert len(api.ops) == 2
    assert [op.method for op in api.ops] == ['UPDATE', 'GET']
    assert a.gcal_uid == old_gcal_uid
    assert a.gcal_hash != old_gcal_hash
    assert gcal_counts(a) == (1,1,0)

def test_gcal_push_sync_2__update_entry_and_accept(testdb):
    u = mkuser('u')
    e1 = mkevent(u, [u.id])
    schedule(e1, e1.window_start, [u.id])
    a = the_attendance(e1)
    sim_push_sync_2(a)
    assert gcal_counts(a) == (1,0,0)
    old_gcal_uid = a.gcal_uid
    old_gcal_hash = a.gcal_hash
    # modify meeting such that calendar entry changes
    schedule(e1, e1.window_start+mins(15), [u.id])
    # calendar entry is no longer accepted
    api = Api(get=[dict(attendees=[dict(email=u.email, responseStatus='needAction')])])
    gcal_sync_event_2(a.id, api)
    db.session.rollback()
    assert len(api.ops) == 3
    assert [op.method for op in api.ops] == ['UPDATE', 'GET', 'UPDATE']
    assert a.gcal_uid == old_gcal_uid
    assert a.gcal_hash != old_gcal_hash
    assert gcal_counts(a) == (1,2,0)

def test_gcal_push_sync_2__avoids_making_redundant_calls(testdb):
    u = mkuser('u')
    e1 = mkevent(u, [u.id])
    schedule(e1, e1.window_start, [u.id])
    a = the_attendance(e1)
    sim_push_sync_2(a)
    assert gcal_counts(a) == (1,0,0)
    # sync unchanged meeting
    api = Api()
    gcal_sync_event_2(a.id, api)
    db.session.rollback()
    # no work done
    assert len(api.ops) == 0
    assert gcal_counts(a) == (1,0,0)

def test_gcal_push_sync_2__remove_entry(testdb):
    u = mkuser('u')
    e1 = mkevent(u, [u.id])
    a = the_attendance(e1)
    schedule(e1, e1.window_start, [u.id])
    sim_push_sync_2(a)
    assert gcal_counts(a) == (1,0,0)
    # meeting becomes unscheduled
    unschedule(e1)
    # sync removed calendar entry
    api = Api()
    gcal_sync_event_2(a.id, api)
    db.session.rollback()
    assert len(api.ops) == 1
    assert [op.method for op in api.ops] == ['DELETE']
    assert a.gcal_uid is None
    assert a.gcal_hash is None
    assert a.gcal_push_id is None
    assert gcal_counts(a) == (1,0,1)
