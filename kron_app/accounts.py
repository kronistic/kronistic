from kron_app import db
from kron_app.utils import uid, flatten
from kron_app.models import User, Email, Contact, AvailabilityEvent
from kron_app.events import events_for
from kron_app.calendars import delete_calendar
from kron_app.gcal_integration import GcalPushState

def all_names(groups):
    assert type(groups) == dict
    return set(flatten(groups.values()))

def remove(user):
    # Sanity checks...
    assert not user.is_removed, 'account already removed'
    # Check for non-empty My Meetings
    assert len(events_for(user).all()) == 0, 'user has active meetings'
    # Check for references to `user` in groups. (Note: inefficient
    # implementation.)
    all_emails = set(email.address for email in user.emails)
    for u in User.query.filter(User.jsongroups!='{}').all():
        assert all_emails.isdisjoint(all_names(u.groups)), 'groups reference user email address'
    # Perform removal...
    for c in user.calendars:
        delete_calendar(c)
    for email in user.emails:
        email.address = f'{uid()}@kronistic.com'
    Contact.query.filter((Contact.user_id==user.id)|(Contact.contact_id==user.id)).delete()
    AvailabilityEvent.query.filter_by(user_id=user.id).delete()
    user.is_removed = True
    user.first_name = 'Deleted'
    user.last_name = 'User'
    user.name = 'Deleted User'
    user.groups = {}
    user.gcal_push_id = None
    user.gcal_push_state = GcalPushState.OFF
    user.virtual_link = None
    db.session.commit()
