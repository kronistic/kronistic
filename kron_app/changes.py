from datetime import timedelta
from sqlalchemy import desc
from sqlalchemy.dialects import postgresql
from kron_app import db
from kron_app.models import Change, Event, EventState, FixedEvent
from kron_app.utils import ids

# When the "change" corresponds to a modified (fixed)event we record the
# event as either `Change.event` or `Change.fixed_event`. This allows us
# to record where the (fixed)event was when the solver last ran,
# without recording subsequent intermediate positions it may take, if
# further modifications are made before the solver next runs.

def record_current(event):
    assert ((type(event) == Event and event.state == EventState.SCHEDULED) or
            (type(event) == FixedEvent))
    if type(event) == Event:
        change = dict(start_at = event.draft_start,
                      end_at = event.draft_end,
                      users = event.draft_attendees,
                      event_id = event.id,
                      conflict = False) # Always removal of SCHEDULED meeting => space freed
    else:
        change = dict(start_at = event.start_at,
                      end_at = event.end_at,
                      users = [event.calendar.user_id],
                      fixed_event_id = event.id,
                      conflict = False)
    stmt = postgresql.insert(Change).values(**change).on_conflict_do_nothing()
    db.session.execute(stmt)

def record_approx_calendar_changes(calendar):
    # Approximate the effect of deleting a calendar by recording a
    # single space spanning the fixed events on the calendar.
    fmin = FixedEvent.query.filter_by(calendar=calendar) \
                           .order_by('start_dt') \
                           .limit(1) \
                           .one_or_none()
    fmax = FixedEvent.query.filter_by(calendar=calendar) \
                           .order_by(desc('end_dt')) \
                           .limit(1) \
                           .one_or_none()
    user = calendar.user
    # The time spanned is extended to compensate for any error
    # incurred when the min/max we find are from all-day events, which
    # have their time-part as local time rather than UTC. This could
    # be tightened by explicitly finding min(/max) timed and all-day
    # events and checking which is sooner(/later), but that won't buy
    # us much.
    maxoffset = timedelta(hours=14)
    if fmin and fmax:
        c = Change(start_at=fmin.start_at-maxoffset,
                   end_at=fmax.end_at+maxoffset,
                   users=[user.id],
                   conflict=False)
        db.session.add(c)

# Used to capture changes to fixed events implied by an update to a
# user's timezone. (Modifying the timezone implicitly shifts all-day
# events.)
#
# For simplicity, we only worry about noticing potential conflicts. We
# don't attempt to ensure that all spaces are recorded, though some
# are.
#
# If we only care about conflicts it's sufficient to concern ourselves
# with only the time window spanned by user's draft meetings. We
# record conflicts for any fixed events overlapping this window. This
# avoids setting the dirty flag on *all* of a user's fixed events. (Of
# which there can easily be >10k.)
#
# To record conflicts for both @kron and regular events we call both
# `record_current` and set the `dirty` flag. (This means we also
# record some spaces, which is fine.)
#
# This is called *before* the timezone is changed so that the
# conflicts recorded for @kron events (by `record_current`) capture
# their pre-move positions.

def record_all_day_event_changes(user):
    mmin = Event.query.filter(Event.state==EventState.SCHEDULED,
                              Event.draft_attendees.contains([user.id])) \
                      .order_by('draft_start') \
                      .limit(1) \
                      .one_or_none()
    mmax = Event.query.filter(Event.state==EventState.SCHEDULED,
                              Event.draft_attendees.contains([user.id])) \
                      .order_by(desc('draft_end')) \
                      .limit(1) \
                      .one_or_none()
    if not (mmin and mmax):
        return
    maxoffset = timedelta(hours=14)
    events = FixedEvent.query \
                       .filter(FixedEvent.all_day==True,
                               FixedEvent.calendar_id.in_(ids(user.calendars)),
                               (mmin.draft_start-maxoffset)<FixedEvent.end_dt,
                               (mmax.draft_end+maxoffset)>FixedEvent.start_dt) \
                       .all()
    for event in events:
        record_current(event)
        event.dirty = True
