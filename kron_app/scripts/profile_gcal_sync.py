#!/usr/bin/env python3

import time, random, cProfile
from uuid import uuid4
from datetime import datetime, timedelta
from kron_app import db, app
from kron_app.models import User, FixedEvent
from kron_app.gcal_integration import to_iso8601, gcal_sync_incremental, gcal_sync_full
from kron_app.tests.test_gcal_sync import sim_api, mkuser

# ./scripts/dbdrop.sh ; ./scripts/dbreset.sh ; ./scripts/profile_gcal_sync.py

# Note: for kalendars sync is now dominated by kron directive parsing.
# For regular calendars, (real) sync is dominated by the http
# requests.

def mkitem(attendees=None):
    uid = str(uuid4())
    start = datetime(2022, 1, 1) + timedelta(hours=random.randint(0, 10000))
    item = {'id': uid,
            'status': 'confirmed',
            'start': {'dateTime': to_iso8601(start)},
            'end': {'dateTime': to_iso8601(start + timedelta(minutes=30))}}
    if attendees is not None:
        item['attendees'] = attendees
    # Test for recurring-event-fixup code path.
    #item['recurringEventId'] = 'foo-bar-baz'
    return item

def main():
    if not app.env == 'development':
        raise Exception('this should only be run in a local dev environment to avoid polluting database')

    random.seed(0)

    u = mkuser(f'jeff@example.com')
    c = u.calendars[0]

    num_users = 5
    users = [mkuser(f'{i}@example.com') for i in range(num_users)]

    def noattendees():
        return None

    def attendees():
        max_attendees = num_users
        n = random.randint(0, max_attendees-1)
        random.shuffle(users)
        emails = [u.email] + [u.email for u in users[:n]]
        return [dict(email=email) for email in emails]

    pages = [[mkitem(attendees=attendees()) for _ in range(1000)] for _ in range(5)]

    # t0 = time.time()
    # result = gcal_sync_incremental(c, sim_api(*pages))
    # elapsed = time.time() - t0
    # print(f'result={result}, elapsed={elapsed}')

    with cProfile.Profile() as pr:
        t0 = time.time()
        result = gcal_sync_incremental(c, sim_api(*pages))
        elapsed = time.time() - t0
    #pr.print_stats('cumtime')
    print(f'result={result}, elapsed={elapsed}')

    print(FixedEvent.query.filter_by(calendar=c).count())
    print([c for c in u.contacts])

if __name__ == '__main__':
    main()
