import re
import time
import itertools
import json
import math
import random
from hashlib import md5
from pprint import pprint
from datetime import datetime, timedelta, timezone
from enum import Enum
from sqlalchemy import func
from dateutil import parser
from dateutil.rrule import rrulestr
from kron_app import app, db
from kron_app.models import User, Calendar, Event, EventState, FixedEvent, Change, Email, GcalSyncLog, GcalResponseState, Attendance, AttendeeResponse, GcalPushState
from kron_app.gcal_api import get_oauth_session_for_user, chk_resp, list_gcal_entries, get_gcal_entry, create_gcal_entry, update_gcal_entry, delete_gcal_entry, watch_gcal_resource, get_gcal_calendar_metadata, list_gcal_settings, get_gcal_setting, GCAL_EVENT_UID_PREFIX, create_gcal_calendar, list_gcal_calendars, stop_gcal_channel, exists_gcal_entry
from kron_app.changes import record_current
from kron_app.poems import make_edit_poem
from kron_app.users import find_user_by_email
from kron_app.utils import tznames, uid, to_utc, ids
import kron_app.mail as mail
from kron_app.kron_directives import parse_kron_directive

# Google calendar integration helpers. (Roughly: code that touches
# both the gcal api and the kron db.)
#
# Sync api docs are here:
#
# https://developers.google.com/calendar/api/guides/sync

def handle_year_0_error(f):
    def g(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            if str(e) == 'year 0 is out of range':
                return datetime.min
            else:
                raise e
    return g

@handle_year_0_error
def from_iso8601(s):
    # Convert to UTC, then drop explicit tz.
    return parser.isoparse(s).astimezone(timezone.utc).replace(tzinfo=None)

@handle_year_0_error
def fromisoformat(s):
    return datetime.fromisoformat(s)

def to_iso8601(utc_datetime):
  # Add explicit timezone so that an offset of
  # `+00:00` is generates by `isoformat`, as required by the api.
  # # https://developers.google.com/calendar/api/v3/reference/events#start
  dt_with_tz = utc_datetime.replace(tzinfo=timezone.utc)
  return datetime.isoformat(dt_with_tz, timespec='seconds')

def is_draft_event(uid):
    return uid.startswith(GCAL_EVENT_UID_PREFIX)

def can_import_gcal_entry(item):
    return ('start' in item and 'end' in item and
            (('dateTime' in item['start'] and 'dateTime' in item['end']) or
             ('date' in item['start'] and 'date' in item['end'])))

def is_free(item):
    if 'transparency' in item and item['transparency'] == 'transparent':
        return True
    elif 'attendees' in item:
        selfs = [a for a in item['attendees'] if 'self' in a and a['self']]
        return selfs and all(a['responseStatus'] != 'accepted' for a in selfs)
    else:
        return False

def get_start_end(item):
    if 'dateTime' in item['start']:
        return (from_iso8601(item['start']['dateTime']),
                from_iso8601(item['end']['dateTime']),
                False)
    else:
        # All-day events
        # https://developers.google.com/calendar/api/v3/reference/events#start
        return (fromisoformat(item['start']['date']),
                fromisoformat(item['end']['date']),
                True)

def is_motion_event(item):
    maybe_motion_task_id = item.get('extendedProperties', {}).get('shared', {}).get('motionTaskId')
    return maybe_motion_task_id is not None

def get_kron_duty_and_costs(item):
    if is_motion_event(item):
        return True, {'everyone': 1}
    summary = item.get('summary') or '' # Guard against `item['summary'] == None`.
    kron_duty, person_cost = parse_kron_directive(summary)
    if kron_duty:
        return kron_duty, person_cost
    else:
        description = item.get('description') or '' # Guard against `item['description'] == None`.
        return parse_kron_directive(description)

def get_attendee_emails(item):
    return [a['email'] for a in item.get('attendees', []) if 'email' in a]

def gcal_list_entries_generator(calendar, incremental=False, single_events=True):
    if incremental and calendar.gcal_sync_token is None:
        raise Exception('sync token must be present to perform an incremental fetch')
    sync_token = calendar.gcal_sync_token if incremental else None
    google = get_oauth_session_for_user(calendar.user)
    next_page_token = None
    while True:
        # Not doing a db commit here, even though list_gcal_settings
        # might have fetched a new token. Instead, leave that to
        # callers. (Often stashing the next_sync_token will take care
        # of this.)
        payload = list_gcal_entries(google, calendar, next_page_token, sync_token, single_events)

        # Always yield an (items_array, result_tuple). This makes the
        # implementation of consumers a a little cleaner. Before a
        # break, set the first element of result tuple to be a status.
        # The second element of the tuple is the (optional)
        # next_sync_token.
        if payload is None:
            yield [], ('full_sync_required', None)
            break
        if 'nextPageToken' in payload:
            next_page_token = payload['nextPageToken']
            yield payload['items'], (None, None)
        else:
            assert 'nextSyncToken' in payload
            yield payload['items'], ('ok', payload['nextSyncToken'])
            break

def differ(fixed_event, item):
    start_dt, end_dt, all_day = get_start_end(item)
    kron_duty, costs =  get_kron_duty_and_costs(item)
    return (fixed_event.start_dt != start_dt or
            fixed_event.end_dt != end_dt or
            fixed_event.all_day != all_day or
            fixed_event.kron_duty != kron_duty or
            fixed_event.costs != costs)

def build_fixed_event(item, calendar):
    f = FixedEvent()
    f.calendar = calendar
    f.uid = item['id']
    f.start_dt, f.end_dt, f.all_day = get_start_end(item)
    f.kron_duty, f.costs =  get_kron_duty_and_costs(item)
    f.dirty = True
    db.session.add(f)
    return f

def get_contact_pairs(item, user, all_emails):
    kron_attendee_emails = (set(e.lower() for e in get_attendee_emails(item)) | {user.email}) & all_emails
    return set(tuple(sorted(pair)) for pair in itertools.combinations(kron_attendee_emails, 2))

def populate_contacts(contact_pairs):
    for email1, email2 in contact_pairs:
        user1 = find_user_by_email(email1)
        user2 = find_user_by_email(email2)
        if user1 is None or user2 is None or user1 == user2:
            continue
        user1.contacts.append(user2)
        user2.contacts.append(user1)
    db.session.commit()

def append_gcal_sync_log(calendar, full, elapsed_secs, num_items, num_changes):
    elapsed = int(elapsed_secs*1000) # ms
    entry = GcalSyncLog(calendar=calendar, full=full, elapsed=elapsed, num_items=num_items, num_changes=num_changes)
    db.session.add(entry)
    db.session.commit()

def gcal_sync_full(calendar, api_calls=None):
    """perform a full sync of a google calendar."""
    t0 = time.time()

    if api_calls is None:
        api_calls = gcal_list_entries_generator(calendar, incremental=False)

    # Any fixed events we don't see in the import will be deleted.
    stmt = db.select([FixedEvent.uid]).filter_by(calendar=calendar)
    fixed_to_delete = set(db.session.execute(stmt).scalars().all())

    # Having `all_emails` in memory is convenient for now, but will
    # breakdown eventually.
    #
    all_emails = set(e.address for e in Email.query.filter(Email.user!=None).all())
    contact_pairs = set()

    num_items = 0
    num_changes = 0

    for items, (_, next_sync_token) in api_calls:
        num_items += len(items)
        uids = [item['id'] for item in items]
        fixed_events = FixedEvent.query \
                                 .filter_by(calendar=calendar) \
                                 .filter(FixedEvent.uid.in_(uids)) \
                                 .all()
        fixed_event_lookup = dict((f.uid,f) for f in fixed_events)
        added = dict()
        for item in items:
            uid = item['id']
            contact_pairs |= get_contact_pairs(item, calendar.user, all_emails)
            kron_duty, costs = get_kron_duty_and_costs(item)
            if is_draft_event(uid):
                pass
            elif (not is_free(item) or kron_duty) and can_import_gcal_entry(item):
                fixed_event = fixed_event_lookup.get(uid)
                if fixed_event is None:
                    assert uid not in fixed_to_delete
                    if uid not in added:
                        # New fixed event.
                        build_fixed_event(item, calendar)
                        added[uid] = item
                        num_changes += 1
                    else:
                        print(f'gcal_sync_full: skipping uid={uid}, calendar_id={calendar.id}, same={added[uid]==item}')
                elif fixed_event is not None and differ(fixed_event, item):
                    # Modified existing fixed event. Record current position then update.
                    record_current(fixed_event)
                    fixed_event.start_dt, fixed_event.end_dt, fixed_event.all_day = get_start_end(item)
                    fixed_event.kron_duty = kron_duty
                    fixed_event.costs = costs
                    fixed_event.dirty = True
                    fixed_to_delete.discard(uid) # Don't delete the new fixed event later!
                    num_changes += 1
                else:
                    # No change to existing fixed event.
                    fixed_to_delete.discard(uid)
        db.session.commit()

    if next_sync_token:
        calendar.gcal_sync_token = next_sync_token
        calendar.gcal_last_sync_at = datetime.utcnow()
    db.session.commit()

    if len(fixed_to_delete) > 0:
        print('will delete the following fixed events:')
        print(fixed_to_delete)
        for f in FixedEvent.query \
                           .filter_by(calendar=calendar) \
                           .filter(FixedEvent.uid.in_(fixed_to_delete)) \
                           .all():
            record_current(f)
            db.session.delete(f)
            num_changes += 1
        db.session.commit()

    populate_contacts(contact_pairs)
    append_gcal_sync_log(calendar, True, time.time() - t0, num_items, num_changes)

class IncSyncResult(Enum):
    full_sync_required = 1
    changes_made = 2
    no_changes_made = 3

def gcal_sync(calendar):
    # Run an incremental sync if possible, otherwise fall back to full
    # sync. Returns a boolean indicating whether changes were made to
    # fixed events.
    result = gcal_sync_incremental(calendar)
    if result == IncSyncResult.full_sync_required:
        gcal_sync_full(calendar)
        return True # TODO: Notice whether we really did change anything?
    else:
        return result == IncSyncResult.changes_made

# pseudo code for revised incremental sync

# if event status == cancelled
#   delete any draft event with this uid and in an 'awaiting delete' state
#   delete any fixed event with this id
# elif not floating event
#   if event is free time # don't need to track free time
#     delete any fixed event with this uid
#   elif can import event # otherwise, assume busy and import (if possible)
#     create / update event with uid
#   else
#     log that we can't handle this event?

# A "tentative" response from an attendee (i.e. selecting "maybe" in
# the UI) is currently counted as free time by Kron. An event itself
# can also have a status of "tentative", which we currently count as
# busy time. (Though I don't know how to put an event in this state.)
# It might turn out we want to treat these two cases similarly.
# https://developers.google.com/calendar/api/v3/reference/events#status

def gcal_sync_incremental(calendar, api_calls=None):
    """perform an incremental sync of a google calendar. an initial full
    sync must already have happened. returns an `IncSyncResult`.
    """
    t0 = time.time()

    sync_token = calendar.gcal_sync_token
    if sync_token is None:
        return IncSyncResult.full_sync_required

    # Allow entries to be fetched from sources other than the api for
    # testing.
    if api_calls is None:
        api_calls = gcal_list_entries_generator(calendar, incremental=True)

    all_emails = set(e.address for e in Email.query.filter(Email.user!=None).all())
    contact_pairs = set()

    num_items = 0
    num_changes = 0
    recurring_events_to_remove = set()

    for items, (status, next_sync_token) in api_calls:
        num_items += len(items)
        uids = [item['id'] for item in items]
        fixed_events = FixedEvent.query \
                                 .filter_by(calendar=calendar) \
                                 .filter(FixedEvent.uid.in_(uids)) \
                                 .all()
        fixed_event_lookup = dict((f.uid,f) for f in fixed_events)
        added = dict()
        for item in items:
            uid = item['id']
            contact_pairs |= get_contact_pairs(item, calendar.user, all_emails)
            if item['status'] == 'cancelled':
                # Calendar entry deleted.
                #
                f = fixed_event_lookup.get(uid)
                if f is not None:
                    record_current(f)
                    db.session.delete(f)
                    num_changes += 1

            elif is_draft_event(uid):
                pass

            else:
                if 'recurringEventId' in item:
                    recurring_events_to_remove.add(item['recurringEventId'])

                kron_duty, costs = get_kron_duty_and_costs(item)
                if is_free(item) and not kron_duty:
                    f = fixed_event_lookup.get(uid)
                    if f is not None:
                        record_current(f)
                        db.session.delete(f)
                        num_changes += 1
                elif can_import_gcal_entry(item):
                    # Busy or free @kron
                    f = fixed_event_lookup.get(uid)
                    if f is None:
                        if uid not in added:
                            # Make a new event.
                            build_fixed_event(item, calendar)
                            added[uid] = item
                            num_changes += 1
                        else:
                            print(f'gcal_sync_incremental: skipping uid={uid}, calendar_id={calendar.id}, same={added[uid]==item}')
                    elif f is not None and differ(f, item):
                        record_current(f)
                        f.start_dt, f.end_dt, f.all_day = get_start_end(item)
                        f.kron_duty = kron_duty
                        f.costs = costs
                        f.dirty = True
                        num_changes += 1
                else:
                    print(f'failed to handle entry uid={uid}')
        db.session.commit()

    if next_sync_token:
        calendar.gcal_sync_token = next_sync_token
        calendar.gcal_last_sync_at = datetime.utcnow()
    db.session.commit()

    # Clean-up after non-recurring events are made to recur (see
    # #117).
    #
    # Unpacked instances of recurring events have their
    # `recurringEventId` set to /the/ (single) underlying event on
    # which the recurrance is specified. This is the event we don't
    # get delete notifications for, so we speculatively attempt to
    # delete it here. This is safe because (a) we ask for unpacked
    # events, so never want the underlying event, (b) this property
    # isn't set on non-recurring events.
    #
    # Note that it's possible for the event we want to delete to be
    # recorded against another of this user's calendars. (This happens
    # if the event is moved between calendars at the same time the
    # recurrence is added.)

    # By deferring this until here, we (a) get to bulk fetch the fixed
    # events, and (b) avoid checking for the same fixed event multiple
    # times. (Which would otherwise happen when a series is modified.)

    if len(recurring_events_to_remove) > 0:
        calendar_ids = [c.id for c in calendar.user.calendars]
        # Record the change because the start/end times might have
        # also changed when the event was made recurring.
        fs = FixedEvent.query \
                       .filter(FixedEvent.calendar_id.in_(calendar_ids),
                               FixedEvent.uid.in_(recurring_events_to_remove)) \
                       .all()
        for f in fs:
            record_current(f)
            db.session.delete(f)
            num_changes += 1
        db.session.commit()

    populate_contacts(contact_pairs)
    append_gcal_sync_log(calendar, False, time.time() - t0, num_items, num_changes)

    if status == 'full_sync_required':
        return IncSyncResult.full_sync_required
    else:
        if num_changes > 0:
            return IncSyncResult.changes_made
        else:
            return IncSyncResult.no_changes_made


# We subscribe to gcal push notifications for
# `GCAL_SUB_TTL_SECS + uniform(0,GCAL_SUB_RENEW_WINDOW)` seconds.
# We renew once we're in last GCAL_SUB_RENEW_WINDOW seconds of
# subscription.
if app.config['ENV'] == 'development':
    GCAL_SUB_TTL_SECS = 5*60
    GCAL_SUB_RENEW_WINDOW = 60
else:
    GCAL_SUB_TTL_SECS = 24*60*60
    GCAL_SUB_RENEW_WINDOW = 60*60

def gcal_subscribe(resource):
    assert type(resource) in (Calendar, User)
    user = resource if type(resource) == User else resource.user
    ttl = GCAL_SUB_TTL_SECS + random.randint(0, GCAL_SUB_RENEW_WINDOW)
    google = get_oauth_session_for_user(user)
    resp = watch_gcal_resource(google, resource, ttl)
    if resp is None or not resp.ok:
        resource.gcal_watch_error_count += 1
        resource.gcal_watch_last_error = resp.text if resp is not None else None
        db.session.commit()
        return
    payload = resp.json()
    expiration_timestamp = int(payload['expiration']) / 1000 # ms:str -> secs:float
    expires_at = datetime.utcfromtimestamp(expiration_timestamp)
    assert len(payload['resourceId']) <= 36
    old_resource_id = resource.gcal_resource_id
    old_channel_id = resource.gcal_channel_id
    resource.gcal_resource_id = payload['resourceId']
    resource.gcal_channel_id = payload['id'] # == uuid
    resource.gcal_channel_expires_at = expires_at
    resource.gcal_watch_last_error = None
    resource.gcal_watch_error_count = 0
    db.session.commit()
    if old_channel_id and old_resource_id:
        # Stop notifications on old channel.
        stop_gcal_channel(google, old_channel_id, old_resource_id)
        db.session.commit() # refresh token
    return payload

def gcal_renew(renew_window=GCAL_SUB_RENEW_WINDOW, dry_run=False):
    threshold = datetime.utcnow() + timedelta(seconds=renew_window)
    resources = []
    for klass in (Calendar, User):
        resources += klass.query \
                          .filter(klass.gcal_channel_id != None) \
                          .where(klass.gcal_channel_expires_at < threshold) \
                          .all()
    for resource in resources:
        user = resource if type(resource) == User else resource.user
        if user.gcal_api_error_count > 0:
            continue
        if not dry_run:
            gcal_subscribe(resource)
        else:
            print(resource)

def gcal_set_gcal_summary(calendar):
    google = get_oauth_session_for_user(calendar.user)
    metadata = get_gcal_calendar_metadata(google, calendar)
    if metadata is None:
        return
    calendar.gcal_summary = metadata['summary']
    db.session.commit()

def gcal_chk_for_cal_and_get_timezone(google):
    """Used during sign-up to check whether the user has a google calendar
    associated with their account, and if so, to fetch the user's
    timezone.

    On success, returns a pair (bool,opt[str]) indicating whether the
    user has a gcal, and an optional tzname.
    """
    resp = get_gcal_setting(google, 'timezone')
    assert resp is not None # Because `google` is not a wrapped oauth session at sign-up.
    if resp.ok:
        tzname = resp.json().get('value')
        # Only use time zones we recognise. An unknown time zone would
        # break the UI (e.g. the time zone select on the profile page)
        # for this user.
        return True, tzname if tzname in tznames() else None
    elif resp.status_code == 403 and 'notACalendarUser' in resp.text:
        # User doesn't have a calendar. (See #300.)
        return False, None
    else:
        # Some un-handled error occurred; raise exception.
        chk_resp(resp)

def hashstr(s):
    h = md5(s.encode()).hexdigest()
    assert len(h) == 32
    return h

def hashobj(obj):
    return hashstr(json.dumps(obj, sort_keys=True))

def get_attendance(event, user_id):
    assert user_id is not None
    return next(a for a in event.attendances if a.email.user_id == user_id)


class GcalApi:
    def get(self, *args, **kwargs):
        return get_gcal_entry(*args, **kwargs)
    def create(self, *args, **kwargs):
        return create_gcal_entry(*args, **kwargs)
    def update(self, *args, **kwargs):
        return update_gcal_entry(*args, **kwargs)
    def delete(self, *args, **kwargs):
        return delete_gcal_entry(*args, **kwargs)
    def exists(self, *args, **kwargs):
        return exists_gcal_entry(*args, **kwargs)


def gcal_event_queue_for(user_id):
    """Returns a query that can be used to fetch the priority ordered
    list of events waiting to be created on gcal.

    """
    attendances = Attendance.query \
                            .join(Event, Email) \
                            .filter(Email.user_id==user_id,
                                    Event.gcal_sync_version==2,
                                    (Event.state==EventState.SCHEDULED)|(Event.state==EventState.PAST),
                                    Attendance.gcal_uid==None).all()
    attendances = [a for a in attendances if do_sync_2_for_this_attendee(user_id, a.event)]
    return sorted([a.event for a in attendances], key=lambda e: e.draft_start)

def gcal_update_api_quotas(utcnow=None):
    if utcnow is None:
        utcnow = datetime.utcnow()
    todrain = []
    # Eventually limit users fetched to just those we need to update.
    for user in User.query.all():
        # We don't need to worry about concurrent changes to
        # gcal_quota since this will always run in the
        # "single-threaded" queue.
        if user.gcal_quota_updated_at + user.gcal_quota_period < utcnow:
            if user.gcal_quota == 0:
                todrain.append(user)
            increment = math.floor((utcnow - user.gcal_quota_updated_at) / user.gcal_quota_period)
            user.gcal_quota = min(user.gcal_quota + increment, user.gcal_quota_max)
            user.gcal_quota_updated_at += increment * user.gcal_quota_period
    db.session.commit()
    # Return the events which can now be sync'd.
    return dict((user.id, ids(gcal_event_queue_for(user.id)[:user.gcal_quota])) for user in todrain)

def gcal_event_data_n_by_1(event, user):
    assert event.is_scheduled() or event.is_past()
    draft_attendees = event.draft_attendees
    unavailable_ids = event.draft_unavailable
    summary = event.title
    if event.is_draft():
        summary += ' [DRAFT]'
    desc = ''
    desc += f'Attendees:<ul>'
    for u in (User.query.get(user_id) for user_id in draft_attendees):
        desc += f'<li>{ u.name }</li>'
    for u in (User.query.get(user_id) for user_id in unavailable_ids):
        desc += f'<li>{ u.name } (Unavailable)</li>'
    desc += '</ul>'
    if event.description and event.description != '<p><br></p>': # special case for html editor empty doc
        desc += event.description
    desc += make_edit_poem(event)
    # By setting guestsCanModify/InviteOther = False we have the gcal
    # UI indicate that changes made to the entry on the primary
    # calendar won't propagate. (Changes made directly on the
    # secondary don't receive the same treatment.)
    attendee = {'email': user.email}
    if user.id in event.draft_attendees:
        attendee['responseStatus'] = 'accepted'
    return {'summary': summary,
            'description': desc,
            'location': event.location,
            'attendees': [attendee] if user.gcal_sync_2_add_self else [],
            'start': {'dateTime': to_iso8601(event.draft_start)},
            'end': {'dateTime': to_iso8601(event.draft_end)},
            'guestsCanModify': False,
            'guestsCanInviteOthers': False,
            'status': 'confirmed'}

# Make gcal entries for (optional) attendees that don't make it?
SYNC_2_IF_UNAVAILABLE = True
def do_sync_2_for_this_attendee(user_id, event):
    return user_id in (event.allattendees if SYNC_2_IF_UNAVAILABLE else event.draft_attendees)

def gcal_sync_event_2(attendance_id, api=None, yank=False):
    """This uses the same rate limiting as the previous implementation of
    gcal sync for create operations. This might not be necessary if we
    stop using our trick of adding a user's primary email as guest, in
    order to have entries propagate from secondary to primary.
    (Because entries with zero guests don't seem to be rate limited in
    the same way.)

    """
    if api is None:
        api = GcalApi()

    a = Attendance.query.get(attendance_id)
    event = a.event
    user = a.email.user
    assert event.gcal_sync_version==2, f'gcal_sync_event_2 can not sync {event}'
    assert user is not None, 'gcal_sync_event_2 cannot sync to gcal for invitees'
    if not user.gcal_sync_enabled:
        return
    if not user.gcal_push_state == GcalPushState.ON:
        return
    google = get_oauth_session_for_user(user)

    # uid and hash track
    assert not ((a.gcal_uid is None) ^ (a.gcal_hash is None))

    if (event.is_scheduled() or event.is_past()) and do_sync_2_for_this_attendee(user.id, event) and not yank:
        # The meeting should appear in this attendee's calendar.
        entry = gcal_event_data_n_by_1(event, user) # NOTE: no id set yet
        entry_hash = hashstr(json.dumps(entry))
        if not a.gcal_uid:

            # We only create the event if the user has a large enough
            # quota to process far enough into the queue to reach this
            # event.
            #
            # Correctness sketch -- this gives the same behaviour as
            # immediately creating all events in the queue, in order,
            # until the quota is exhausted (which seems more obviously
            # correct) for the following reasons:
            #
            # 1. This event would be created iff the condition checked
            # here is met.
            #
            # 2. The other events in the queue will be serviced by
            # other tasks, so we don't have to worry about them here.
            # Each will have had an its own `gcal_sync_event` task
            # queued. That will create the event if possible, else we
            # don't have a large enough quota, in which case
            # `task_gcal_drain_event_queue` will create the event
            # eventually.
            queue = ids(gcal_event_queue_for(user.id))
            if event.id in queue[:user.gcal_quota]: # Could add a `limit` to the query instead?
                # Create a new calendar entry.
                entry['id'] = GCAL_EVENT_UID_PREFIX + uid()
                gcal_uid = api.create(google, user.gcal_push_id, entry)
                if not gcal_uid is None:
                    a.gcal_uid = gcal_uid
                    a.gcal_hash = entry_hash
                    a.gcal_push_id = user.gcal_push_id
                    user.gcal_quota -= 1
                    a.gcal_create_count += 1
                db.session.commit() # refresh token

        elif entry_hash != a.gcal_hash:
            # Existing entry needs updating.
            assert user.gcal_push_id == a.gcal_push_id
            api.update(google, user.gcal_push_id, entry, a.gcal_uid)
            # TODO: handle failure
            a.gcal_hash = entry_hash
            a.gcal_update_count += 1
            db.session.commit() # refresh token

            if user.id in event.draft_attendees: # We don't set to accepted when attendee is unavailable.
                # Check response is set to "accepted" and fix if not.
                resp = api.get(google, user.gcal_push_id, a.gcal_uid)
                assert resp, 'no response from get_gcal_entry' # Eventually we'd like an exception here to trigger task retry.
                db.session.commit() # refresh token

                response_status = next((a for a in resp.get('attendees', []) if a.get('email') == user.email), {}).get('responseStatus')
                if response_status != 'accepted':
                    api.update(google, user.gcal_push_id, entry, a.gcal_uid)
                    a.gcal_update_count += 1
                    db.session.commit()

    elif a.gcal_uid:
        assert user.gcal_push_id == a.gcal_push_id
        api.delete(google, user.gcal_push_id, a.gcal_uid)
        # TODO: handle failure
        a.gcal_uid = None
        a.gcal_hash = None
        a.gcal_push_id = None
        a.gcal_delete_count += 1
        db.session.commit() # refresh token


def gcal_create_calendar_for_push(user):
    KRON_CALENDAR_SUMMARY = 'kalendar'
    assert user.gcal_push_state == GcalPushState.CREATING
    google = get_oauth_session_for_user(user)

    # Re-use any existing "kalendar" while in local development. (To
    # avoid cluttering up gcal.)
    if app.config['ENV'] == 'development':
        items, result = gcal_list_calendars(user, show_hidden=True)
        for item in items:
            if item.get('summary') == KRON_CALENDAR_SUMMARY:
                gcal_id = item['id']
                user.gcal_push_id = gcal_id
                user.gcal_push_state = GcalPushState.ON
                db.session.commit()
                return

    # Make a calendar.
    gcal_id = create_gcal_calendar(google, KRON_CALENDAR_SUMMARY, timezone=user.tzname)
    user.gcal_push_id = gcal_id
    user.gcal_push_state = GcalPushState.ON
    db.session.commit()

def gcal_list_calendars_generator(user, show_deleted=False, show_hidden=False):
    google = get_oauth_session_for_user(user)
    next_page_token = None
    while True:
        payload = list_gcal_calendars(google, show_deleted, show_hidden, page_token=next_page_token)
        if payload is None:
            yield [], 'error'
            break
        elif 'nextPageToken' in payload:
            next_page_token = payload['nextPageToken']
            yield payload['items'], None
        else:
            yield payload['items'], 'ok'
            break

def gcal_list_calendars(*args, **kwargs):
    out = []
    for items, result in gcal_list_calendars_generator(*args, **kwargs):
        out.extend(items)
    db.session.commit() # refresh token
    return out, result

def push_gone(user):
    assert user.gcal_push_id is not None
    items, result = gcal_list_calendars(user, show_hidden=True)
    assert result == 'ok', f'failed to fetch calendar list for {user}'
    assert len(items) > 0 # sanity check
    return user.gcal_push_id not in [item['id'] for item in items]

def record_push_gone(user):
    attendances = Attendance.query \
                            .filter_by(email=user.primary_email,
                                       gcal_push_id=user.gcal_push_id) \
                            .all()
    for a in attendances:
        a.gcal_uid = None
        a.gcal_hash = None
        a.gcal_push_id = None
    user.gcal_push_state = GcalPushState.OFF
    user.gcal_push_id = None
    db.session.commit()

def gcal_handle_user_notification(user):
    if not user.gcal_push_state == GcalPushState.ON:
        return
    if push_gone(user):
        record_push_gone(user)
        return True # signal that push gcal has gone
