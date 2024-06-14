#!/usr/bin/env PYTHONINSPECT=x python3

from datetime import datetime, timedelta
from pprint import pprint
from kron_app.models import User, Contact, Email, Calendar, EventState, Event, Series, FixedEvent, SolverLog, ErrorLog, GcalSyncLog, Change, Attendance
from kron_app.models import AvailabilityEvent as AEvent
from kron_app import db
from kron_app.utils import from_utc, to_utc
utcnow = datetime.utcnow
def user(id):
    return User.query.get(id)
