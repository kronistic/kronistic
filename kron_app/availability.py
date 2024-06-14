import math
from enum import IntEnum, unique
from datetime import datetime, timedelta, date, time
from dateutil.tz import gettz
from sqlalchemy import desc
from kron_app.models import Change, AvailabilityEvent as AEvent, Calendar, Event, EventState, Attendance, FixedEvent
from kron_app.utils import to_utc, from_utc, dotdict, ids
from kron_app.events import events_for
from kron_app import db

# TODO: i'm currently ignoring the fact that to_utc is not defined
# everywhere / unambiguous. i expect the consequences of this to be
# incorrect behaviour around DST changes. e.g. it might be that user
# supplied data won't round-trip correctly. (i.e. the fetched bitmap
# isn't identical to the written bitmap.)
# - related: the apparent length (as seen in the bitmap) of occurences
#   are constant in local time, but can vary in e.g. utc, again
#   because of dst boundaries.

# TODO: there are now a bunch of methods that take something like
# `local_start` + `tzname`. it probably makes sense to bundle these
# together as a datetime with tzinfo. this doesn't make the underlying
# implementation any easy, but it's probably a little neater.


# Availability Events
# -------------------
#
# 1. start_at / end_at are in local time, which is indicated by tzname.
# 2. events recur weekly in local time. i.e. at start_at + n*1wk.
# 3. recur_end_at marks the end of the last occurrence (so this is eq.
# to end_at for one-off events), and should always be end_at + N*1wk
# for N>=0.
# 4. where an event repeats indefinitely, recur_end_at is None
# 5. a user having overlapping availability events is tolerated in the
# db, even though the ui can't distinguish / write (=> round-trip) such.
# 6. off-grain events are tolerated in the db

# note that start times of occurrences are only guaranteed to be 1wk
# apart in local time. in e.g. utc, gaps can be more or less than this
# when dst boundaries are crossed.

# note: The motivation for support overlapping availability events is
# to make it easy to import availability from gcal, which does contain
# overlaps. If we later choose to remove this, one approach might be
# to find the overlaps and then use `api_get_availability() ;
# api_set_availability()` to re-write those sections, resulting in no
# overlaps.


# Finite costs (free, free if needed, etc.) align with existing fixed
# event costs. Defining UNAVAILABLE as some large value means that
# `new_cost > old_cost` tells us whether a change of availability
# should record a conflict or space.
UNAVAILABLE = 9

grain = timedelta(minutes=15)
maxoffset = timedelta(hours=14)

def on_grain(dt):
    # assumes that the start of each day is on-grain
    assert type(dt) == datetime
    return ((dt - dt.replace(hour=0, minute=0, second=0, microsecond=0)) % grain) == timedelta()

def is_naive_dt(x):
    return type(x) == datetime and x.tzinfo is None

def d_to_dt(d):
    assert type(d) == date
    return datetime(d.year, d.month, d.day, tzinfo=None)

class Occurence:
    def __init__(self, start_at, end_at, user_id, tzname, cost):
        self.start_at = start_at
        self.end_at = end_at
        self.user_id = user_id
        self.tzname = tzname
        self.cost = cost
    @property
    def utc_start_at(self):
        return to_utc(self.start_at, self.tz)
    @property
    def utc_end_at(self):
        return to_utc(self.end_at, self.tz)
    @property
    def utc_recur_end_at(self):
        return to_utc(self.recur_end_at, self.tz)
    @property
    def tz(self):
        return gettz(self.tzname)
    def __repr__(self):
        return f'<Occurence start_at={repr(self.start_at)} end_at={repr(self.end_at)} tzname={repr(self.tzname)} cost={repr(self.cost)}>'
    def to_fixed_event(self):
        assert 0 <= self.cost < UNAVAILABLE
        return dotdict(kind='availability',
                       start_at=self.utc_start_at,
                       end_at=self.utc_end_at,
                       kron_duty=True,
                       costs=dict(everyone=self.cost),
                       calendar=dict(user_id=self.user_id))

def occurences(aevent):
    cur_start_at = aevent.start_at # semantics of recurrence is repetitions in local time
    cur_end_at = aevent.end_at # end time is preserved, not necessarily length
    unbounded = aevent.recur_end_at is None
    while unbounded or cur_end_at <= aevent.recur_end_at:
        yield Occurence(cur_start_at, cur_end_at, aevent.user_id, aevent.tzname, aevent.cost)
        cur_start_at += timedelta(days=7)
        cur_end_at += timedelta(days=7)

def overlaps(instance, utc_window_start, utc_window_end):
    return (utc_window_end is None or instance.utc_start_at < utc_window_end) and instance.utc_end_at > utc_window_start

# TODO: could this accept and directly query using local times, to
# avoid widening the window by `maxoffset`?
def get_overlapping(utc_window_start, utc_window_end, user_ids):
    out = []
    candidates = AEvent.query \
                       .filter(AEvent.user_id.in_(user_ids)) \
                       .filter(AEvent.start_at < (utc_window_end+maxoffset)) \
                       .filter((AEvent.recur_end_at == None) | (AEvent.recur_end_at > (utc_window_start-maxoffset))) \
                       .all()
    for c in candidates:
        for i in occurences(c):
            if i.utc_start_at > utc_window_end:
                break
            if overlaps(i, utc_window_start, utc_window_end):
                out.append(i)
    return out

@unique
class EventBitmap(IntEnum):
    FREE = 0
    IFNEEDED = 1
    BUSY = 2

# TODO: There's a common core shared by get_*_bitmap methods -- maybe
# consolidate.
def get_events_bitmap(user, local_start, tzname, length):
    assert is_naive_dt(local_start)
    assert on_grain(local_start)
    assert length >= 0
    tz = gettz(tzname) # the tz associated with local_start
    local_end = local_start + length*grain
    utc_window_start = to_utc(local_start, tz)
    utc_window_end = to_utc(local_end, tz)

    calendar_ids = ids(Calendar.query.filter(Calendar.user_id.in_([user.id])).all())
    fixed_events = FixedEvent.query \
                             .filter((utc_window_start-maxoffset<FixedEvent.end_dt), (utc_window_end+maxoffset>FixedEvent.start_dt)) \
                             .filter(FixedEvent.calendar_id.in_(calendar_ids)) \
                             .all()
    # Only show fixed events that incur a cost to schedule over. (This
    # anticipates the planned change to @kron semantics to "graded
    # transparency".)
    # NOTE: no attempt is made to handle groups here.
    fixed_events = [f for f in fixed_events if not f.kron_duty or f.costs.get('everyone', 0) > 0]
    fixed_events = [f for f in fixed_events if utc_window_start<f.end_at and utc_window_end>f.start_at]

    data = [EventBitmap.FREE] * length

    for f in fixed_events:
        # Pessimistically round fixed events to grain, to match how
        # the solver ought to work (#477)
        start_ix = math.floor((max(local_start, from_utc(f.start_at, tz)) - local_start) / grain)
        end_ix = math.ceil((min(local_end, from_utc(f.end_at, tz)) - local_start) / grain)
        for ix in range(start_ix, end_ix):
            # We lump all degrees of graded transparency together as
            # 'ifneeded' for now.
            data[ix] = max(data[ix], EventBitmap.IFNEEDED if f.kron_duty else EventBitmap.BUSY)

    return data

def get_meetings_bitmap(user, local_start, tzname, length):
    assert is_naive_dt(local_start)
    assert on_grain(local_start)
    assert length >= 0
    tz = gettz(tzname) # the tz associated with local_start
    local_end = local_start + length*grain
    utc_window_start = to_utc(local_start, tz)
    utc_window_end = to_utc(local_end, tz)
    # I'm not yet entirely sure what the right thing here is. Meetings
    # disappearing throughout the day is a little odd, and might need
    # changing. However, having PAST meetings appear just like future
    # meetings is potentially confusing, since they're no longer
    # dynamic. Perhaps past meetings should look more like fixed
    # events? Perhaps we only show today's PAST meetings?
    events = events_for(user, include_past=False) \
        .filter((Event.state == EventState.SCHEDULED) | (Event.state == EventState.PAST),
                Event.draft_attendees.contains([user.id]),
                utc_window_start < Event.draft_end,
                utc_window_end > Event.draft_start).all()
    data = [EventBitmap.FREE] * length
    for e in events:
        start_ix = math.floor((max(local_start, from_utc(e.draft_start, tz)) - local_start) / grain)
        end_ix = math.ceil((min(local_end, from_utc(e.draft_end, tz)) - local_start) / grain)
        data[start_ix:end_ix] = [EventBitmap.BUSY] * (end_ix-start_ix)

    return data

def make_splits(i, utc_window_start, utc_window_end):
    # we already know this instance overlaps...
    assert overlaps(i, utc_window_start, utc_window_end)
    # ... so there are two cases (for the bounded case) where we might need to add an aevent:
    if i.utc_start_at < utc_window_start:
        end_at = from_utc(utc_window_start, i.tz)
        a = AEvent(user_id=i.user_id,
                   tzname=i.tzname,
                   start_at=i.start_at,
                   end_at=end_at,
                   recur_end_at=end_at,
                   cost=i.cost)
        db.session.add(a)
    if utc_window_end is not None and i.utc_end_at > utc_window_end:
        a = AEvent(user_id=i.user_id,
                   tzname=i.tzname,
                   start_at=from_utc(utc_window_end, i.tz),
                   end_at=i.end_at,
                   recur_end_at=i.end_at,
                   cost=i.cost)
        db.session.add(a)

# TODO: do this arithmetic, rather than generate and test?
def clear_window(utc_window_start, utc_window_end, user_id):
    candidates = AEvent.query \
                       .filter_by(user_id=user_id) \
                       .filter((AEvent.recur_end_at == None) | (AEvent.recur_end_at > (utc_window_start-maxoffset))) \
                       .filter(AEvent.start_at < (utc_window_end+maxoffset)) \
                       .all()
    for c in candidates:
        lastgood = None # remember lastgood, so we can patch up. if no last good, delete
        for i in occurences(c):
            if i.utc_end_at < utc_window_start:
                lastgood = i
            elif overlaps(i, utc_window_start, utc_window_end):
                make_splits(i, utc_window_start, utc_window_end)
            else:
                # we've found first occurrence after the window. make a new recurring event starting here.
                a = AEvent(user_id=user_id,
                           tzname=c.tzname,
                           start_at=i.start_at,
                           end_at=i.end_at,
                           recur_end_at=c.recur_end_at,
                           cost=c.cost)
                db.session.add(a)
                break
        if lastgood is None:
            db.session.delete(c)
        else:
            # set recurrence to end here
            c.recur_end_at = lastgood.end_at


def clear_window_unbounded(utc_window_start, user_id):
    candidates = AEvent.query \
                       .filter_by(user_id=user_id) \
                       .filter((AEvent.recur_end_at == None) | (AEvent.recur_end_at > (utc_window_start-maxoffset))) \
                       .all()
    for c in candidates:
        local_window_start = from_utc(utc_window_start, c.tz)
        if c.recur_end_at is not None and c.recur_end_at <= local_window_start: # finishes before (or at) boundary; keep entire thing
            # Ignore anything that doesn't overlap the window. The
            # query doesn't already do this because we use an extended
            # window to accomodate timezone variation. (It plausible
            # that this is redundnant given the rest of the
            # implementation, but I'm not sure, so better to be
            # explicit.)
            continue
        elif local_window_start <= c.start_at: # starts on or after boundary, so remove entirely
            db.session.delete(c)
        else: # straddles boundary
            assert c.start_at < local_window_start and c.recur_end_at is None or c.recur_end_at > local_window_start

            # adjust end of recurrence, or delete where no whole recurrences remain
            if local_window_start < c.end_at:
                db.session.delete(c)
            else:
                reps = (local_window_start - c.end_at) // timedelta(days=7)
                c.recur_end_at = c.end_at + reps*timedelta(days=7)

            # check whether we split an occurrence
            start_to_boundary = local_window_start - c.start_at
            nwks = start_to_boundary // timedelta(days=7)
            rem = start_to_boundary % timedelta(days=7)
            assert nwks >= 0
            assert rem >= timedelta()
            if rem < (c.end_at-c.start_at): # boundary splits occurrence
                start_at = c.start_at + timedelta(days=7)*nwks
                end_at = start_at + rem
                a = AEvent(user_id=user_id,
                           tzname=c.tzname,
                           start_at=start_at,
                           end_at=end_at,
                           recur_end_at=end_at,
                           cost=c.cost)
                db.session.add(a)


def get_bitmap(user, local_start, tzname, length):
    assert is_naive_dt(local_start)
    assert on_grain(local_start)
    assert length >= 0
    tz = gettz(tzname) # the tz associated with local_start
    local_end = local_start + length*grain
    utc_window_start = to_utc(local_start, tz)
    utc_window_end = to_utc(local_end, tz)
    # NOTE utc_window_end - utc_window_start might not == length*grain

    occurs = get_overlapping(utc_window_start, utc_window_end, [user.id])

    data = [UNAVAILABLE] * length

    for occurence in occurs:
        start_ix = math.floor((max(local_start, from_utc(occurence.utc_start_at, tz)) - local_start) / grain)
        end_ix = math.ceil((min(local_end, from_utc(occurence.utc_end_at, tz)) - local_start) / grain)
        for ix in range(start_ix, end_ix):
            data[ix] = (0 if data[ix] == UNAVAILABLE else data[ix]) + occurence.cost

    return data

def contig(data):
    assert len(data) > 0
    out = []
    partial = (data[0], 0) # (val, start)
    for i, val in enumerate(data[1:]):
        if val != partial[0]:
            out.append(dict(val=partial[0], start=partial[1], end=i+1))
            partial = (val, i+1)
    out.append(dict(val=partial[0], start=partial[1], end=len(data)))
    return out

def set_bitmap(user, local_start, tzname, bitmap, recur=False):
    assert is_naive_dt(local_start)
    assert on_grain(local_start) # we expect this to be the case, even though the implementation might work otherwise
    for chunk in contig(bitmap):
        if chunk['val'] == UNAVAILABLE:
            continue
        start_at = local_start + chunk['start']*grain
        end_at = local_start + chunk['end']*grain
        recur_end_at = None if recur else end_at
        a = AEvent(user_id=user.id,
                   start_at=start_at,
                   end_at=end_at,
                   recur_end_at=recur_end_at,
                   tzname=tzname,
                   cost=chunk['val'])
        db.session.add(a)


# IDEA: one can imagine doing this on a more coarse grid (> 15 min) --
# this is fine for now though.

# Note that `record_changes` doesn't do the right thing in the
# presence of overlapping @kron events, though this won't matter if we
# change the semantics of @kron to mean "graded transparency".
#
# (Here's an example where the wrong thing happens. Imagine some
# ifneeded time in the UI overlapping "@kron free" time in gcal. If
# the ifneeded is changed to busy, `record_changes` will see this as a
# conflict. However, the solver actually sees ifneeded+"@kron free" =
# ifneeded before the change, and busy+"@kron free" = free after the
# change, so this is actually a space opening up.)

def record_changes(user, local_start, tzname, bitmap, recur):
    assert is_naive_dt(local_start)
    tz = gettz(tzname) # the tz associated with local_start
    utc_start = to_utc(local_start, tz)
    e = events_for(user).order_by(desc('window_end')).limit(1).one_or_none()
    if e and e.window_end > utc_start:
        if recur:
            week_len = timedelta(days=7) // grain
            assert len(bitmap) <= week_len
            bitmap = bitmap + ([UNAVAILABLE] * (week_len-len(bitmap))) # pad to week
            assert len(bitmap) == week_len
            l = math.ceil((e.window_end - utc_start) / grain)
            new_bitmap = (bitmap * math.ceil(l / len(bitmap)))[:l] # replicate
            assert len(new_bitmap) == l
        else:
            new_bitmap = bitmap
        if len(new_bitmap) > 0:
            old_bitmap = get_bitmap(user, local_start, tzname, len(new_bitmap))
            raw_changes = diff_bitmaps(old_bitmap, new_bitmap)
            for r in raw_changes:
                start_at = to_utc(local_start + grain*r['start'], tz)
                end_at = to_utc(local_start + grain*r['end'], tz)
                # Note that the solver can run concurrently with this.
                c = Change(start_at=start_at, end_at=end_at, users=[user.id], conflict=r['val'])
                # print((start_at, end_at, cur>prev))
                db.session.add(c)

def diff_bitmaps(frm, to):
    assert len(frm) == len(to)
    def f(cur,prev):
        if cur==prev:
            return None # no change
        elif cur>prev:
            return True # conflict
        else:
            return False # space
    return [c for c in contig(list(f(cur, prev) for prev,cur in zip(frm,to))) if not c['val'] is None]

# web app entry points

def api_get_availability(user, d):
    l = 24 * 7 * 4
    dt = d_to_dt(d)
    availability = get_bitmap(user, dt, user.tzname, l)
    events = get_events_bitmap(user, dt, user.tzname, l)
    meetings = get_meetings_bitmap(user, dt, user.tzname, l)
    return availability, events, meetings

def api_set_availability(user, d, bitmap, recur):
    assert len(bitmap) == 24 * 7 * 4
    assert all(0 <= x <= UNAVAILABLE for x in bitmap)
    local_start = d_to_dt(d)
    local_end = local_start + timedelta(days=7)
    utc_start = to_utc(local_start, user.tz)
    utc_end = to_utc(local_end, user.tz)
    record_changes(user, local_start, user.tzname, bitmap, recur)
    if recur:
        clear_window_unbounded(utc_start, user.id)
    else:
        clear_window(utc_start, utc_end, user.id)
    set_bitmap(user, local_start, user.tzname, bitmap, recur)
    db.session.commit()


def add_core_availability(user, start_time, end_time, days, utcnow=None):
    assert type(start_time) is int
    assert type(end_time) is int
    assert type(days) is list
    if utcnow is None:
        utcnow = datetime.utcnow()
    is_naive_dt(utcnow)
    today = from_utc(utcnow, user.tz).date()
    start_ix = today.weekday() # monday = 0
    for i in range(7):
        ix = (start_ix + i) % 7
        if ix in days:
            d = today + timedelta(days=i)
            a = AEvent(user=user,
                       tzname=user.tzname,
                       start_at=datetime.combine(d, time(start_time)),
                       end_at=datetime.combine(d, time(end_time)),
                       recur_end_at=None,
                       cost=0)
            db.session.add(a)
