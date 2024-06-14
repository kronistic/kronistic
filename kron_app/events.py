from datetime import date, datetime, timedelta
from dateutil import rrule
import itertools
from collections import defaultdict
from sqlalchemy import select, or_, func
from sqlalchemy.dialects import postgresql
from kron_app import app, db
from kron_app.models import Event, EventState, Series, User, Email, Attendance, AttendeeResponse
from kron_app.users import find_user_by_email
from kron_app.utils import ids, uid, uid32, to_utc
from kron_app.changes import record_current


# Event states

# UNSCHEDULED (either new or unscheduled by solver)
#   conditions:
#     no (required) invitees
#     all (required and optional) attendees have sync active calendar
#     draft_start / draft_end / draft_attendees all clear

# SCHEDULED (has draft start/end etc. set by solver)
#   conditions:
#     no (required) invitees.
#     all (required and optional) attendees have sync active calendar
#     draft_start / draft_end / draft_attendees all set

# TODO: The name HOLD might be better now. (This is the state used to
# HOLD meetings rather than send them to the solver.)

# PENDING (waiting for invitees to sign-up and/or calendars to sync or
# declined by required attendee)
#   conditions:
#     draft_start / draft_end / draft_attendees all clear

# FINALIZED (freeze daemon makes final DRAFT -> FINALIZED transition)
#   conditions:
#     same as draft (since can only get to finalized from draft)
#

# DELETED (from any state except finalized)
#   initiated by web UI, where the `hidden` flag is set. finished via queue.
#   conditions:
#     none:

# PAST (only from SCHEDULED with final=True, aka FINAL)
#   transitioned by freeze daemon once a FINAL meeting ends.
#   Such a meeting has draft times, etc. since it came from SCHEDULED.

# The `final` flag distinguishes between two types of SCHEDULED
# events, and has no meaning outside of that. DRAFT events have
# `final=False` and transition to FINAL (`final=True`) when they
# (first) cross their freeze horizon. This happens at most once, even
# if a final meeting is rescheduled such that the freeze horizon is
# again in the future.

# The dirty flag's meaning is only defined for events in the INIT,
# SCHEDULED or UNSCHEDULED states. In the INIT state the dirty flag is
# typically set, but not always -- run_solver clears the dirty flag
# before a solve, but only after the solve will the state transition
# out of INIT. Any queries that filter on dirty need to be conditioned
# to only include meetings in those states. (It's tempting to replace
# the flag with explicit INIT_DIRTY, SCHEDULED_DIRTY and UNSCHEDULED_DIRTY
# states to make this explicit.)

def all_attendees_setup(event):
    users = User.query.filter(User.id.in_(event.attendees + event.optionalattendees)).all()
    return all(u.setup_complete for u in users)

# Transition into / out of pending, depending on invitees and
# attendees calendar sync state. These are the state transitions that
# we're concerned with when creating / updating events in the web app.
def set_state(event):
    if event.is_finalized() or event.is_deleted() or event.is_past():
        return
    if event.invitees == [] and all_attendees_setup(event) and event.required_attendee_decline_count == 0:
        # FINALIZED/DELETED/PAST: doesn't get here
        # INIT or UNSCHEDULED or SCHEDULED: no change
        # PENDING => INIT (has to be this, it's the only transition out of pending)
        if event.is_pending():
            event.state = EventState.INIT
            event.dirty = True
    else:
        # Record change on SCHEDULED -> PENDING.
        if event.state == EventState.SCHEDULED:
            record_current(event)
        # Set to pending state.
        event.state = EventState.PENDING
        event.draft_start = None
        event.draft_end = None
        event.draft_attendees = []

def get_email(address):
    # I was nervous about using using upsert unconditionally and
    # burning through serial numbers everytime `update_attendees`
    # looks at an email.
    # https://dba.stackexchange.com/a/295356
    # Do this extra check for now:
    address = address.lower()
    email = Email.query.filter_by(address=address).one_or_none()
    if email:
        return email
    else:
        # https://docs.sqlalchemy.org/en/14/orm/persistence_techniques.html#using-postgresql-on-conflict-with-returning-to-return-upserted-orm-objects
        stmt = postgresql.insert(Email).values([dict(address=address,invite=True,uid=uid32())]).on_conflict_do_nothing().returning(Email)
        orm_stmt = select(Email).from_statement(stmt).execution_options(populate_existing=True)
        email = db.session.execute(orm_stmt).scalar_one_or_none()
        assert email, 'wah!'
        return email

def update_attendees(event, theattendees):
    # Check which emails have been removed, and set the deleted flag
    # for those.
    emails = {a['email'].lower() for a in theattendees}
    for a in event.attendances:
        if a.email.address not in emails:
            a.deleted = True
    # Insert / update attendees that are present.
    for email, opt in ((get_email(a['email']), a['optional']) for a in theattendees):
        if not (email.user is None or email.user.primary_email == email):
            email = email.user.primary_email
        a = next((a for a in event.attendances if a.email == email), None)
        if not a:
            a = Attendance(event=event, email=email, creator=event.creator)
            db.session.add(a)
        a.optional = opt
        a.deleted = False

def update_attendee_priority(event, user_id, priority):
    attendence = next((a for a in event.attendances if a.email.user_id == user_id), None)
    if attendence:
      attendence.priority = priority

def build_event(**event_data):
    event = Event()
    # Only for new events.
    event.creator = event_data['creator']
    # Shared with `update_event`.
    event.length_in_mins = event_data['length_in_mins']
    event.tzname = event_data['tzname']
    event.window_start_local = event_data['window_start_local']
    event.window_end_local = event_data['window_end_local']
    event.window_start = to_utc(event_data['window_start_local'], event.tz)
    event.window_end = to_utc(event_data['window_end_local'], event.tz)
    event.freeze_horizon_in_days = event_data['freeze_horizon_in_days']
    event.title = event_data['title']
    event.description = event_data['description']
    event.location = event_data['location']
    event.series = event_data.get('series', None)
    update_attendees(event, event_data.get('theattendees', []))
    set_state(event)
    db.session.add(event)
    return event

def update_event(event, **event_data):
    # Set event_data.
    event.length_in_mins = event_data['length_in_mins']
    event.tzname = event_data['tzname']
    event.window_start_local = event_data['window_start_local']
    event.window_end_local = event_data['window_end_local']
    event.window_start = to_utc(event_data['window_start_local'], event.tz)
    event.window_end = to_utc(event_data['window_end_local'], event.tz)
    event.freeze_horizon_in_days = event_data['freeze_horizon_in_days']
    event.title = event_data['title']
    event.description = event_data['description']
    event.location = event_data['location']
    old_attendees = set(event.attendees+event.optionalattendees)
    old_invitees = set(event.invitees+event.optionalinvitees)
    update_attendees(event, event_data.get('theattendees', []))
    new_attendees = list(set(event.attendees+event.optionalattendees) - old_attendees)
    new_invitees = list(set(event.invitees+event.optionalinvitees) - old_invitees)
    # TODO: Be smarter -- only set when something salient changes.
    # (Actually, this is tricky, since we rely on the solver to
    # initiate draft event sync. i.e. If we don't set the flag when
    # e.g. only the title changes, the new title won't propagate to
    # calendars.)
    event.dirty = True
    # Set event state.
    was_draft = event.is_scheduled()
    set_state(event)
    # Did we do from draft -> pending?
    # (draft -> unscheduled doesn't happen with `set_state`)
    made_pending = was_draft and event.is_pending()
    return made_pending, new_attendees, new_invitees

def expand_weekly(start, end, n):
    wk = timedelta(days=7)
    return [(start+(wk*i), end+(wk*i)) for i in range(n)]

def build_weekly_series(event_data, n):
    windows = expand_weekly(event_data['window_start_local'], event_data['window_end_local'], n)
    event_data_without_window = dict((k,v) for k,v in event_data.items()
                                     if k not in ['window_start_local', 'window_end_local'])
    series = Series()
    db.session.add(series)
    events = [build_event(window_start_local=window_start_local,
                          window_end_local=window_end_local,
                          series=series,
                          **event_data_without_window)
              for (window_start_local, window_end_local) in windows]
    return series

def build_rrule_series(event_data, rrstr="FREQ=WEEKLY;INTERVAL=1;COUNT=5"):
    #build windows for sequences based on applying rrule to window_start and stop.
    # trim the windows so they don't overlap 
    rrstart = rrule.rrulestr(rrstr,dtstart=event_data['window_start_local'])
    rrend = rrule.rrulestr(rrstr,dtstart=event_data['window_end_local'])
    
    windows = []
    rs=list(enumerate(rrstart))
    for i,r in rs:
        windows.append( (r, min(rrend[i], rrstart[i+1]) if i<len(rs)-1 else rrend[i]) )

    # windows = expand_weekly(event_data['window_start_local'], event_data['window_end_local'], n)
    event_data_without_window = dict((k,v) for k,v in event_data.items()
                                     if k not in ['window_start_local', 'window_end_local'])
    series = Series()
    db.session.add(series)
    events = [build_event(window_start_local=window_start_local,
                          window_end_local=window_end_local,
                          series=series,
                          **event_data_without_window)
              for (window_start_local, window_end_local) in windows]
    return series

def delete_event(event_id):
    event = Event.query.get(event_id)
    if event is None or event.state in [EventState.DELETED, EventState.FINALIZED, EventState.PAST]:
        return
    if event.state == EventState.SCHEDULED:
        record_current(event)
    event.state = EventState.DELETED
    db.session.commit()

def past_horizon():
    utcnow = func.timezone('utc', func.now())
    query = Event.query \
                 .filter_by(state=EventState.SCHEDULED, final=False) \
                 .where(Event.draft_start - Event.freeze_horizon < utcnow)
    return query.all()

def past_draft_end():
    utcnow = func.timezone('utc', func.now())
    query = Event.query \
                 .filter_by(state=EventState.SCHEDULED, final=True) \
                 .where(Event.draft_end < utcnow)
    return query.all()

def past_window_end():
    utcnow = func.timezone('utc', func.now())
    query = Event.query \
                 .filter((Event.state==EventState.PENDING)|(Event.state==EventState.UNSCHEDULED)) \
                 .where(Event.window_end < utcnow)
    return query.all()

# Note that `event_for(u).count()` doesn't work as expected:
# https://github.com/kronistic/kron-app/issues/636
def events_for(user, include_past=False):
  q = Event.query \
           .join(Event.attendances, isouter=True) \
           .filter((Event.creator_id == user.id) |
                   ((Attendance.email_id==user.primary_email_id) &
                    (Attendance.deleted==False) &
                    (Attendance.response!=AttendeeResponse.NO)),
                   Event.state != EventState.FINALIZED,
                   Event.state != EventState.DELETED,
                   Event.hidden == False)
  if not include_past:
      q = q.filter(Event.state != EventState.PAST)
  return q

def invited_to(email):
    assert email.user is None, 'not an invite' # not strictly necessary, but matches how this is used in practice
    return Event.query \
                .join(Event.attendances) \
                .filter(Event.state != EventState.FINALIZED,
                        Event.state != EventState.DELETED,
                        Event.state != EventState.PAST,
                        Event.hidden == False,
                        Attendance.email_id == email.id,
                        Attendance.deleted == False) \
                .all()

def event_for_update(event_id):
    stmt = select(Event).where(Event.id==event_id).with_for_update()
    return db.session.execute(stmt).scalar_one_or_none()

# Throughout this module we do read-modify-write operations on each
# event in a collection. This is a convenient way to make each
# individual step atomic. I'm making each step it's own transaction,
# otherwise I'd be taking multiple locks and would have to worry about
# deadlocks.
def iter_with_for_update(event_ids):
    for event_id in event_ids:
        event = event_for_update(event_id)
        if event:
            yield event
            db.session.commit() # release lock

# Events that were previously scheduled can become INIT or PENDING
# here. The ids of such meetings are in the return value. (Events made
# PENDING are typically re-scheduled once the new user's calendar is
# sync'd.)

# We don't want to show a user a draft time that doesn't take
# their schedule into account. For new sign ups this is
# achieved by ensuring all of the new user's meetings are made
# PENDING.

# The semantics of PENDING are currently such that it doesn't
# make sense to do this for aliases. i.e. We only keep things
# in PENDING while waiting for a sign up or waiting for
# attendees' calendars to sync, neither of which hold (in
# general) when adding an alias.

# The solution is to have a special case here that puts any
# SCHEDULED events back into the INIT state when adding an alias.
# This ensure we don't show stale times to the user. (Note: an
# event can only be SCHEDULED after calling `set_state` when
# adding an alias. Events for new users are always PENDING, as
# mentioned earlier.) This also entails setting the dirty
# flag, ensuring the solver looks at these next time it runs.

# Other states events might be in when adding an alias:

# INIT: Will look OK in my meetings, and will be marked dirty.

# PENDING: Will look OK in my meetings. Likely waiting on
# other users to sign-up and will be scheduled when that
# happens. Could be waiting for an initial calendar sync to
# happen (inc. of the user adding the alias) but that process
# will take care or having the solver run once sync has
# finished. So nothing to do here.

# UNSCHEDULED: Will look OK in my meetings. Adding an alias
# can only make the scheduling problem harder, so there's no
# need to flag as dirty to request re-solve. (Since adding an
# alias never moves a user from required to optional.)

# What we're doing here is similar to this suggestion:
# https://github.com/kronistic/kron-app/issues/374#issuecomment-1209155364
#
# Once we have that, we might reconsider what we're doing
# here. (Although I'm not sure we can achieve what we do here
# with a view change -- it would be tricky to differentiate
# between the cases where an optional attendee is
# intentionally left out of a meeting, and the case where the
# solver hasn't run since they were added.)

def invitee_to_attendee_fixup(user, email):
    # When making a new user at sign-up we'll have `user.primary_email
    # == email`. (In which case we're calling this to set meetings
    # states)

    # Before adding an alias we'll have `email.user is None`, which
    # implies `email not in user.emails`. (In which case we call this
    # to merge/re-point attendances and set meeting states.) By
    # calling this, we ensure that by adding an alias we don't violate
    # the condition that `attendance.email` is either a user's primary
    # email or has its `user` property set to `None`.

    assert (user.primary_email == email) or (email.user is None and email not in user.emails)

    attendances = Attendance.query.filter_by(email=email).all()
    tosync = []
    for a, event in ((a, a.event) for a in attendances):
        # Re-point invites to user.
        if email != user.primary_email:
            pa = next((a for a in event.attendances if a.email==user.primary_email), None)
            if pa:
                # Merge attendances.
                if not a.deleted:
                    pa.optional = a.optional if pa.deleted else pa.optional and a.optional
                pa.deleted = pa.deleted and a.deleted
                event.attendances.remove(a)
                db.session.delete(a)
            else:
                # Not an attendee. Re-point existing attendance to primary email.
                a.email = user.primary_email

        if not a.deleted:

            for user_id in event.allattendees:
                if user_id == user.id:
                    continue
                other = User.query.get(user_id)

                db.session.flush() # Workaround for #654.
                if other not in user.contacts:
                    user.contacts.append(other)
                if user not in other.contacts:
                    other.contacts.append(user)

            # Set meeting state. If the invite is deleted, no state
            # change is necessary. (Argument: If there is no attendee,
            # either deleted or not present, then the user isn't
            # attending, so nothing has changed. If the user is
            # already an attendee, then we don't modify their
            # optionality, so nothing has changed with the meeting
            # that would require a state change.)

            was_scheduled = event.is_scheduled()
            set_state(event)

            if event.is_scheduled():
                record_current(event)
                event.state = EventState.INIT
                event.draft_start = None
                event.draft_end = None
                event.draft_attendees = []
                event.dirty = True

            # Arrange for a draft event sync to run whenever an event is
            # moved out of SCHEDULED.
            if was_scheduled and not event.is_scheduled():
                tosync.append(event.id)

    db.session.commit()
    return tosync

# Here's an argument for why this catches everything we care about:

# If nothing change between user sign-up (`invitee_to_attendee_fixup`)
# and this running (after calendar sync) then we're good. The new user
# must be an (optional)attendee on the meetings they were added to --
# this finds those and transitions the state if possible.

# Any meetings the user was remove from between sign-up and this been
# called will be taken care of by the regular update meeting flow.

# Any meetings the user was added to after sign-up will be handled by
# the regular create meeting flow.

def move_from_pending(user):
    # Pending events the user is attending.
    events = Event.query \
                  .join(Event.attendances) \
                  .filter(Attendance.email==user.primary_email,
                          Attendance.deleted==False, \
                          Event.state==EventState.PENDING) \
                  .all()
    state_changes = False
    # For pending events, pending -> init is the only
    # transition that set_state can make.
    for event in iter_with_for_update(ids(events)):
        assert event.is_pending()
        set_state(event)
        assert event.is_pending() or event.is_init()
        if event.is_init():
            state_changes = True
    return state_changes

def decline(email):
    events = invited_to(email)
    # TODO: It looks like this will re-send to creator's of previously
    # declined emails, not just the creators of the set of meetings
    # declining at this instant. We can fix this when we consolidate
    # the attendee & invitee decline mechanisms.
    creators = list(set(e.creator for e in events))
    email.declined = list(set(email.declined + ids(events)))
    db.session.commit()
    return creators

def set_attendee_response(event, user, response):
    if user == event.creator and response == AttendeeResponse.NO:
        raise Exception('creator cannot decline their own meeting')
    a = next(a for a in event.attendances if a.email.user == user)
    assert a, 'user is not an attendee'
    a.response = response
    set_state(event)
    event.dirty = True

def populate_contacts(event):
    allattendees = User.query.filter(User.id.in_(event.allattendees)).all()
    for u1, u2 in itertools.combinations(allattendees, 2):
        u1.contacts.append(u2)
        u2.contacts.append(u1)
    db.session.commit()
