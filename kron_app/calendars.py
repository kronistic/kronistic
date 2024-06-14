from sqlalchemy import update, delete
from kron_app import db
from kron_app.models import Calendar, FixedEvent, GcalSyncLog
from kron_app.changes import record_approx_calendar_changes

def delete_calendar(calendar):
    record_approx_calendar_changes(calendar)
    # Perform the delete directly rather than with
    # `db.session.delete()` to avoid loading potentially large numbers
    # of associated records (fixed events, sync log) into memory.
    # (#771)
    stmt = delete(FixedEvent).where(FixedEvent.calendar_id==calendar.id)
    db.session.execute(stmt)
    stmt = update(GcalSyncLog).values(calendar_id=None).where(GcalSyncLog.calendar_id==calendar.id)
    db.session.execute(stmt)
    stmt = delete(Calendar).where(Calendar.id==calendar.id)
    db.session.execute(stmt)
