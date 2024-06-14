from datetime import datetime
from sqlalchemy import or_
from kron_app import celery, db
from kron_app.models import User, Calendar, Event, EventState, ErrorLog, Email, GcalPushState
from kron_app.gcal_api import get_oauth_session_for_user, stop_gcal_channel
from kron_app.gcal_integration import gcal_renew, gcal_sync, gcal_sync_full, gcal_subscribe, gcal_set_gcal_summary, gcal_sync_event_2, gcal_create_calendar_for_push, gcal_update_api_quotas, gcal_list_calendars, gcal_handle_user_notification
from kron_app.events import past_horizon, past_draft_end, past_window_end, delete_event, events_for
from kron_app.run_solver import run_solver
from kron_app.events import move_from_pending, delete_event, populate_contacts
from kron_app.changes import record_current
from kron_app.smtp import sendmail
import kron_app.mail as mail

def log_error(task, exception, task_id, args, kwargs, einfo):
    db.session.rollback()
    e = ErrorLog()
    e.data = dict(src='task',
                  detail=dict(name=task.name, args=args, kwargs=kwargs),
                  exception=type(exception).__name__,
                  tb=str(einfo))
    db.session.add(e)
    db.session.commit()

@celery.task(on_failure=log_error)
def task_test_error(*args, **kwargs):
    raise Exception('test error')

@celery.task(on_failure=log_error)
def task_sendmail(mail):
    sendmail(mail)

@celery.task(on_failure=log_error)
def task_send_solver_email(email, event_id, expected_state):
    event = Event.query.get(event_id)
    assert event
    if expected_state is None or event.state == expected_state:
        sendmail(email)

@celery.task(on_failure=log_error)
def task_gcal_renew():
    gcal_renew()

@celery.task(on_failure=log_error)
def task_timed_state_changes():
    # DRAFT -> FINAL
    for event in past_horizon():
        task_freeze(event.id)
    # FINAL -> PAST
    for event in past_draft_end():
        task_archive(event.id)
    for event in past_window_end():
        assert event.state in [EventState.PENDING, EventState.UNSCHEDULED]
        assert event.window_end < datetime.utcnow()
        event.state = EventState.DELETED
        db.session.commit()

@celery.task(on_failure=log_error)
def task_freeze(event_id):
    event = Event.query.get(event_id)
    assert event
    if not event.is_draft():
        return
    event.final = True
    db.session.commit()
    task_gcal_sync_event.delay(event_id)
    # Send email.
    for user_id in event.draft_attendees:
        user = User.query.get(user_id)
        if user.send_freeze_notifications:
            task_sendmail.delay(mail.meeting_finalized(user, event))

@celery.task(on_failure=log_error)
def task_archive(event_id):
    event = Event.query.get(event_id)
    assert event and event.is_final()
    event.state = EventState.PAST
    db.session.commit()

# We don't make any assumptions about the order in which the sign up
# tasks (`task_post_signup` and `task_post_setup`) will run. Instead,
# they both check whether they have completed user set-up and should
# therefore proceed to set-up meetings.
def complete_setup(user):
    if user.setup_complete:
        return
    # More explicit checks would be better.
    def post_signup_complete():
        return user.gcal_channel_id is not None
    def exited_setup():
        return user.setup_step is None
    if post_signup_complete() and exited_setup():
        # Flag as complete, setup meetings etc.
        user.setup_complete = True
        db.session.commit()
        runsolver = move_from_pending(user)
        if runsolver:
            task_run_solver.delay()
        task_sendmail.delay(mail.welcome(user))

@celery.task(on_failure=log_error)
def task_post_signup(user_id, tosync):
    user = User.query.get(user_id)
    # Add pull from primary.
    calendar = Calendar(user=user, gcal_id='primary', gcal_summary=user.email)
    db.session.add(calendar)
    db.session.commit()
    gcal_set_gcal_summary(calendar)
    gcal_sync(calendar)
    gcal_subscribe(calendar)
    # Perhaps something changed between full sync and subscribe.
    gcal_sync(calendar)

    # Add gcal to push meetings to.
    gcal_create_calendar_for_push(user)

    # Subscribe to calendar list notifications.
    gcal_subscribe(user)

    # Perform draft event sync on meetings made pending when this user
    # signed up.
    #
    # I think we have to do this -- even though it's likely that the
    # event will be reschedule once the solver runs, it's *possible*
    # that something else will happen that will keep the event pending
    # for a long period of time. e.g. Another invitee is added. Should
    # that happen, we don't want to leave stale draft events in
    # calendars.
    #
    for event_id in tosync:
        task_gcal_sync_event.delay(event_id)

    complete_setup(user)

@celery.task(on_failure=log_error)
def task_post_setup(user_id):
    user = User.query.get(user_id)
    complete_setup(user)

@celery.task(on_failure=log_error)
def task_enable_push(user_id):
    user = User.query.get(user_id)
    gcal_create_calendar_for_push(user)
    for e in events_for(user).all():
        task_gcal_sync_event.delay(e.id)

@celery.task(on_failure=log_error)
def task_post_signin(user_id):
    pass

@celery.task(on_failure=log_error)
def task_post_calendar_notification(calendar_id):
    calendar = Calendar.query.get(calendar_id)
    changes_made = gcal_sync(calendar)
    if changes_made:
        task_run_solver.delay()

@celery.task(on_failure=log_error)
def task_post_user_notification(user_id):
    user = User.query.get(user_id)
    if gcal_handle_user_notification(user):
        task_sendmail.delay(mail.kalendar_repair(user))

@celery.task(on_failure=log_error)
def task_post_create_events(event_ids, attendees_to_notify, invitees_to_notify, run_solver):
    assert len(event_ids) >= 1
    event = Event.query.get(event_ids[0])
    if run_solver:
        task_run_solver.delay()
    for user_id in attendees_to_notify:
        user = User.query.get(user_id)
        if user.send_new_meeting_notifications:
            task_sendmail.delay(mail.new_meeting(event, user))
    for email_id in invitees_to_notify:
        email = Email.query.get(email_id)
        task_sendmail.delay(mail.invite_to_meeting(event, email))
    populate_contacts(event)

# Treating required / optional invitees uniformly keeps things simple
# -- we only need to worry about sending a notification when an
# invitee is added. If we do something different for required /
# optional, then we have to decide what to do about the case where an
# existing inviteed moves from e.g. required to optional.
@celery.task(on_failure=log_error)
def task_post_modify_event(event_id, attendees_to_notify, invitees_to_notify, made_pending):
    event = Event.query.get(event_id)
    task_run_solver.delay()
    for user_id in attendees_to_notify:
        user = User.query.get(user_id)
        if user.send_new_meeting_notifications:
            task_sendmail.delay(mail.new_meeting(event, user))
    for email_id in invitees_to_notify:
        email = Email.query.get(email_id)
        if event_id not in email.declined:
            task_sendmail.delay(mail.invite_to_meeting(event, email))
    if made_pending:
        task_gcal_sync_event.delay(event_id)
    populate_contacts(event)

@celery.task(on_failure=log_error)
def task_delete_events(event_ids):
    for event_id in event_ids:
        delete_event(event_id)
        task_gcal_sync_event.delay(event_id)
    task_run_solver.delay()

@celery.task(on_failure=log_error)
def task_post_decline_meeting(user_id, event_ids, send_notification):
    assert len(event_ids) > 0
    task_run_solver.delay()
    # A meeting may have moved into PENDING, and therefore a calendar
    # sync may be required. We trigger the sync task for all meetings
    # for simplicity. (The sync task will avoid doing redundant work.)
    for event_id in event_ids:
        task_gcal_sync_event.delay(event_id)
    event = Event.query.get(event_ids[0])
    user = User.query.get(user_id)
    if send_notification:
        task_sendmail.delay(mail.meeting_declined(event, user))

@celery.task(on_failure=log_error)
def task_post_decline_invite(email_id, user_ids):
    email = Email.query.get(email_id)
    if email:
        for user in User.query.filter(User.id.in_(user_ids)).all():
            task_sendmail.delay(mail.invite_declined(user, email))

@celery.task(on_failure=log_error)
def task_post_add_alias(tosync):
    for event_id in tosync:
        task_gcal_sync_event.delay(event_id)
    task_run_solver.delay()

@celery.task(on_failure=log_error)
def task_post_modify_user_timezone():
    task_run_solver.delay()

@celery.task(on_failure=log_error)
def task_post_modify_groups(user_id, group_names):
    pass

# TODO: Specify a rate limit. i.e. Limit the number of times the
# solver runs in some period of time.
# https://docs.celeryq.dev/en/stable/userguide/tasks.html#Task.rate_limit
@celery.task(on_failure=log_error)
def task_run_solver():
    # Ensure that all events that are past their freeze horizon have
    # the final flag set when the solver runs. Otherwise we can hit
    # the issue described in #515.
    now = datetime.utcnow()
    for event in past_horizon():
        task_freeze(event.id)
    tosync, emails = run_solver(now=now)
    for event_id in tosync:
        task_gcal_sync_event.delay(event_id)
    for args in emails:
        task_send_solver_email.apply_async(args[:-1], countdown=args[-1])

@celery.task(on_failure=log_error)
def task_post_add_calendar(calendar_id):
    calendar = Calendar.query.get(calendar_id)
    if calendar is None:
        return
    gcal_sync(calendar)
    gcal_subscribe(calendar)
    gcal_sync(calendar)
    task_run_solver.delay()

@celery.task(on_failure=log_error)
def task_post_delete_calendar(user_id, gcal_channel_id, gcal_resource_id):
    task_run_solver.delay()
    if gcal_channel_id and gcal_resource_id:
        user = User.query.get(user_id)
        if user:
            google = get_oauth_session_for_user(user)
            stop_gcal_channel(google, gcal_channel_id, gcal_resource_id)
            db.session.commit()

@celery.task(on_failure=log_error)
def task_gcal_sync(calendar_id, full):
    calendar = Calendar.query.get(calendar_id)
    if full:
        gcal_sync_full(calendar)
    else:
        gcal_sync(calendar)
    db.session.commit() # perhaps we refreshed the oauth token

@celery.task(on_failure=log_error)
def task_gcal_sync_event(event_id, yank=False):
    event = Event.query.get(event_id)
    assert event and event.gcal_sync_version == 2
    for a in (a for a in event.attendances if a.email.user is not None):
        task_gcal_sync_event_2.delay(a.id, yank)

@celery.task(on_failure=log_error)
def task_gcal_sync_event_2(attendance_id, yank):
    gcal_sync_event_2(attendance_id, yank=yank)

@celery.task(on_failure=log_error)
def task_gcal_update_api_quotas():
    """
    Runs periodically to maintain (local) gcal api quotas.
    """
    for event_ids in gcal_update_api_quotas().values():
        for event_id in event_ids:
            task_gcal_sync_event.delay(event_id)

@celery.task(on_failure=log_error)
def task_purge_task_table():
    """
    Runs periodically to remove completed tasks from the database.
    """
    db.session.execute("DELETE FROM kombu_message WHERE visible = false AND "
                       "timestamp < (SELECT NOW()::timestamp - interval '1 hour');")
    db.session.commit()
