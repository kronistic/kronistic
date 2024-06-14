#!/usr/bin/env python3

import json
import argparse
from datetime import datetime, timedelta, time
from pprint import pprint
from kron_app import db
from kron_app.models import User, Calendar, Event, EventState, Contact, Attendance, GcalPushState
from kron_app.tasks import task_run_solver, task_gcal_sync, task_freeze, task_archive, task_gcal_sync_event, task_enable_push, task_purge_task_table
from kron_app.gcal_integration import gcal_sync_full, gcal_sync_incremental, gcal_subscribe, gcal_renew, gcal_list_entries_generator, gcal_list_calendars
from kron_app.gcal_api import get_oauth_session_for_user, list_gcal_settings, patch_gcal_calendar_list, gcal_revoke
from kron_app.events import invited_to
from kron_app.accounts import remove as remove_account
from kron_app.utils import ids

def do_solve(skip_queue):
    fn = task_run_solver if skip_queue else task_run_solver.delay
    print(fn())

def do_sync(calendar_id, full, skip_queue):
    fn = task_gcal_sync if skip_queue else task_gcal_sync.delay
    print(fn(calendar_id, full))

def do_freeze(event_id):
    task_freeze.delay(event_id)

def do_archive(event_id):
    task_archive.delay(event_id)

def do_list_events(calendar_id, verbose):
    calendar = Calendar.query.get(calendar_id)
    for items, result in gcal_list_entries_generator(calendar, incremental=False):
        for item in items:
            obj = item if verbose else (item['id'], item['status'])
            print(obj)
    print(result)
    db.session.commit() # perhaps we refreshed the oauth token

def do_list_calendars(user_id):
    user = User.query.get(user_id)
    items, result = gcal_list_calendars(user, show_hidden=True)
    pprint(items)
    print(result)

def do_list_settings(user_id):
    user = User.query.get(user_id)
    google = get_oauth_session_for_user(user)
    payload = list_gcal_settings(google)
    db.session.commit()
    if payload is not None:
        for item in payload['items']:
            print(f"{item['id']} = {item['value']}")

def do_subscribe(resource):
    resource_class, resource_id = resource.split('#')
    assert resource_class in ('calendar', 'user')
    resource = dict(calendar=Calendar, user=User)[resource_class].query.get(resource_id)
    payload = gcal_subscribe(resource)
    pprint(payload)

def do_renew(renew_window, dry_run):
    gcal_renew(renew_window, dry_run)

def do_remove_account(user_id):
    user = User.query.get(user_id)
    assert user
    print(f'about to *remove* the account of "{user.name}" ({user.email})!')
    if confirm():
        remove_account(user)

def do_revoke_token(user_id):
    user = User.query.get(user_id)
    assert user
    print(f'about to revoke token of "{user.name}" ({user.email})!')
    if confirm():
        token = json.loads(user.tokens)
        resp = gcal_revoke(token)
        print(resp)
        if resp.ok:
            user.tokens = '{}'
            db.session.commit()
        else:
            print(resp.text)

# TODO: fix skip-queue, which doesn't work as expected because
# `task_gcal_sync_event` queues sub-tasks that aren't aware of this
# flag.
def do_push(event_id, yank, skip_queue):
    gcal_sync_event = task_gcal_sync_event if skip_queue else task_gcal_sync_event.delay
    gcal_sync_event(event_id, yank=yank)

def do_enable_push(user_id, skip_queue):
    user = User.query.get(user_id)
    assert user.gcal_push_state == GcalPushState.OFF, 'already configured'
    current_user.gcal_push_state = GcalPushState.CREATING
    db.session.commit()
    fn = task_enable_push if skip_queue else task_enable_push.delay
    print(fn(user_id))

def do_purge_task_table(skip_queue):
    (task_purge_task_table if skip_queue else task_purge_task_table.delay)()

def confirm():
    resp = input('proceed? (yes/no) ')
    if resp == 'yes':
        return True
    elif resp == 'no':
        return False
    else:
        return confirm()

def posint(s):
    i = int(s)
    if i <= 0: raise ValueError
    return i

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)

    parser_solve = subparsers.add_parser('solve', help='Run the solver.')
    parser_solve.add_argument('--skip-queue', action='store_true', help='skip task queue')
    parser_solve.set_defaults(fn=do_solve)

    parser_sync = subparsers.add_parser('sync', help='Sync a user\'s Google calendar.')
    parser_sync.add_argument('calendar_id', type=posint)
    parser_sync.add_argument('-f', '--full', action='store_true', help='perform a full sync')
    parser_sync.add_argument('--skip-queue', action='store_true', help='skip task queue')
    parser_sync.set_defaults(fn=do_sync)

    parser_freeze_event = subparsers.add_parser('freeze', help='Unconditionally finalize an event.')
    parser_freeze_event.add_argument('event_id', type=posint)
    parser_freeze_event.set_defaults(fn=do_freeze)

    parser_archive_event = subparsers.add_parser('archive', help='Unconditionally archive an event.')
    parser_archive_event.add_argument('event_id', type=posint)
    parser_archive_event.set_defaults(fn=do_archive)

    parser_list_events = subparsers.add_parser('list_events', help='Show all events on a calendar.')
    parser_list_events.add_argument('calendar_id', type=posint)
    parser_list_events.add_argument('-v', '--verbose', action='store_true', help='show event details')
    parser_list_events.set_defaults(fn=do_list_events)

    parser_list_calendars = subparsers.add_parser('list_calendars', help='Show the user\'s Google calendar list.')
    parser_list_calendars.add_argument('user_id', type=posint)
    parser_list_calendars.set_defaults(fn=do_list_calendars)

    parser_list_settings = subparsers.add_parser('list_settings', help='Show the user\'s Google calendar settings.')
    parser_list_settings.add_argument('user_id', type=posint)
    parser_list_settings.set_defaults(fn=do_list_settings)

    parser_subscribe = subparsers.add_parser('sub', help='Subscribe to push notifications.')
    parser_subscribe.add_argument('resource', type=str, help='Calendar or User, given as either calendar#id or user#id.')
    parser_subscribe.set_defaults(fn=do_subscribe)

    parser_renew = subparsers.add_parser('renew', help='Renew all (about to expire) push notification subscriptions.')
    parser_renew.add_argument('renew_window', type=posint, help='(seconds)')
    parser_renew.add_argument('--dry-run', action='store_true')
    parser_renew.set_defaults(fn=do_renew)

    parser_remove_account = subparsers.add_parser('remove_account', help='Remove account.')
    parser_remove_account.add_argument('user_id', type=posint)
    parser_remove_account.set_defaults(fn=do_remove_account)

    parser_revoke_token = subparsers.add_parser('revoke_token', help='Revoke token.')
    parser_revoke_token.add_argument('user_id', type=posint)
    parser_revoke_token.set_defaults(fn=do_revoke_token)

    parser_push = subparsers.add_parser('push', help='Push event(s) to gcal')
    parser_push.add_argument('event_id', type=posint)
    parser_push.add_argument('--yank', action='store_true', help='yank event from calendar')
    parser_push.add_argument('--skip-queue', action='store_true', help='skip task queue')
    parser_push.set_defaults(fn=do_push)

    parser_enable_push = subparsers.add_parser('enable_push', help='Enable pushing meetings to gcal for user.')
    parser_enable_push.add_argument('user_id', type=posint)
    parser_enable_push.add_argument('--skip-queue', action='store_true', help='skip task queue')
    parser_enable_push.set_defaults(fn=do_enable_push)

    parser_purge_task_table = subparsers.add_parser('purge_task_table', help='Remove completed tasks from the database.')
    parser_purge_task_table.add_argument('--skip-queue', action='store_true', help='skip task queue')
    parser_purge_task_table.set_defaults(fn=do_purge_task_table)

    args = parser.parse_args()
    args.fn(**{k:v for k,v in vars(args).items() if not k in ['command', 'fn']})
