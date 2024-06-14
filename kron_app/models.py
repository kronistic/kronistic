import json
from enum import IntEnum, unique
import numpy as np
from sqlalchemy.dialects import postgresql
from kron_app import db
from kron_app import login_manager
from kron_app.utils import to_utc
from datetime import datetime, timedelta
from dateutil.tz import gettz
from flask_login import UserMixin

@login_manager.user_loader
def load_user(id):
  user = User.query.get(int(id))
  return user if user and not user.is_removed else None

def gcal_is_free_account(email):
  return any(email.endswith(s) for s in ['@gmail.com', '@googlemail.com'])

def gcal_quota_max(free):
  return 200 if free else 1000

def email_from_ctx(ctx):
  email_id = ctx.get_current_parameters()['primary_email_id']
  return Email.query.get(email_id) if email_id else None

def default_gcal_quota(ctx):
  email = email_from_ctx(ctx)
  free = not email or gcal_is_free_account(email.address)
  return gcal_quota_max(free)

def default_gcal_quota_period(ctx):
  email = email_from_ctx(ctx)
  free = not email or gcal_is_free_account(email.address)
  return timedelta(minutes=180 if free else 15)

@unique
class GcalPushState(IntEnum):
  OFF = 0
  CREATING = 1
  ON = 2

class User(db.Model, UserMixin):
  __tablename__ = 'users'
  id = db.Column(db.Integer, primary_key = True)
  # TODO: Make name fields non-nullable. To save having to handle both
  # None and '' everywhere.
  name = db.Column(db.String(100), nullable = True)
  first_name = db.Column(db.String(100), nullable = True)
  last_name = db.Column(db.String(100), nullable = True)
  # should we generate poems (via openai) for this user?
  poems = db.Column(db.Boolean, nullable = False, default = True)
  # stores access and refresh tokens JSON dumped as string
  tokens = db.Column(db.Text)
  created_at = db.Column(db.DateTime, default = datetime.utcnow)
  # TODO: Make this non-nullable once populated for all users?
  last_login_at = db.Column(db.DateTime, nullable = True)
  # preferences for meetings (stored as JSON)
  preferences = db.Column(
    db.Text, 
    default = '{"weekend":"0","startTime":"09:00:00","endTime":"17:00:00","offset":7}')
  # I don't know that there's a defined max length for IANA timezone
  # names. The longest name currently in the db is 32 characters. The
  # typical format is either 'x/x' or 'x/x/x' where x has max length
  # of 14 characters. This gives a max total length of 44. I'm bumping
  # that to 48 for extra margin.
  tzname = db.Column(db.String(48), nullable=False, default='America/Los_Angeles')
  _active_calendar_id = db.Column(db.Integer) # TODO: drop
  calendars = db.relationship('Calendar', foreign_keys='Calendar.user_id', back_populates = 'user')
  @property
  def primary_calendar(self):
    return next((c for c in self.calendars if c.is_gcal_primary()), None)
  # virtual link e.g. zoom or google hangouts
  virtual_link = db.Column(db.String(256), nullable = True)
  # pointer to created events
  events = db.relationship('Event', back_populates = 'creator')
  gcal_api_error_count = db.Column(db.Integer, nullable = False, default = 0)
  gcal_quota = db.Column(db.Integer, nullable = False, default = default_gcal_quota)
  gcal_quota_updated_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
  gcal_quota_period = db.Column(db.Interval, nullable = False, default = default_gcal_quota_period)
  gcal_resource_id = db.Column(db.String(36), nullable = True)
  gcal_channel_id = db.Column(db.String(36), nullable = True, unique = True)
  gcal_channel_expires_at = db.Column(db.DateTime, nullable = True)
  gcal_watch_error_count = db.Column(db.Integer, nullable = False, default = 0)
  gcal_watch_last_error = db.Column(db.Text, nullable = True)
  send_new_meeting_notifications = db.Column(db.Boolean, nullable = False, default = True)
  send_freeze_notifications = db.Column(db.Boolean, nullable = False, default = True)
  is_admin = db.Column(db.Boolean, nullable = False, default = False)
  is_removed = db.Column(db.Boolean, nullable = False, default = False)
  setup_json = db.Column(db.Text, nullable=True)
  setup_step = db.Column(db.Integer, nullable=True, default=0)
  setup_complete = db.Column(db.Boolean, nullable=False, default=False)
  _kalendar_gcal_id = db.Column(db.String(1024), nullable=True) # TODO: drop
  gcal_push_id = db.Column(db.String(1024), nullable=True)
  gcal_push_state = db.Column(db.Integer, nullable=False, default=GcalPushState.CREATING)
  @property
  def gcal_push_state_name(self):
    return GcalPushState(self.gcal_push_state).name
  gcal_sync_2_add_self = db.Column(db.Boolean, nullable = False, default = True)
  gcal_sync_enabled = db.Column(db.Boolean, nullable = False, default = True)
  contacts = db.relationship('User',
                             secondary='contacts',
                             primaryjoin='User.id==Contact.user_id',
                             secondaryjoin='User.id==Contact.contact_id',
                             order_by='User.name')
  primary_email_id = db.Column(db.Integer, db.ForeignKey('emails.id', name='users_primary_email_id_fkey'), nullable=False)
  primary_email = db.relationship('Email', foreign_keys=[primary_email_id], back_populates='user')
  emails = db.relationship('Email', foreign_keys='Email.user_id', back_populates='user')
  availability_events = db.relationship('AvailabilityEvent', back_populates = 'user')
  jsongroups = db.Column(db.Text, nullable = False, default='{}')
  @property
  def groups(self):
    return json.loads(self.jsongroups)
  @groups.setter
  def groups(self, val):
    self.jsongroups = json.dumps(val)

  @property
  def email(self):
    return self.primary_email and self.primary_email.address
  @email.setter
  def email(self, address):
    if self.primary_email is None:
      self.primary_email = Email()
    self.primary_email.address = address
  @property
  def aliases(self):
    return [email.address for email in self.emails if email != self.primary_email]
  @property
  def prefs_start_time(self):
    return json.loads(self.preferences)['startTime']
  @property
  def prefs_end_time(self):
    return json.loads(self.preferences)['endTime']
  @property
  def tz(self):
    return gettz(self.tzname)
  @property
  def setup_data(self):
    return json.loads(self.setup_json) if self.setup_json else None
  @property
  def invited(self):
    return any(email.invite for email in self.emails)
  @property
  def gcal_is_free_account(self):
    return gcal_is_free_account(self.email)
  @property
  def gcal_quota_max(self):
    return gcal_quota_max(self.gcal_is_free_account)


class Contact(db.Model):
  __tablename__ = 'contacts'
  user_id = db.Column('user_id', db.ForeignKey('users.id'), primary_key=True)
  contact_id = db.Column('contact_id', db.ForeignKey('users.id'), primary_key=True)

class Email(db.Model):
  __tablename__ = 'emails'
  id = db.Column(db.Integer, primary_key = True)
  # Always stored lower case.
  address = db.Column(db.String(100), unique=True, nullable=False)
  user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='emails_user_id_fkey', use_alter=True), nullable=True)
  user = db.relationship('User', foreign_keys=[user_id], post_update=True)
  uid = db.Column(db.String(32), unique = True, nullable = True)
  declined = db.Column(postgresql.ARRAY(db.Integer), nullable=False, default=[])
  invite = db.Column(db.Boolean, nullable=False, default=False)
  tokens = db.Column(db.Text)
  sign_up_steps_json = db.Column(db.Text, nullable=False, default='[]')
  created_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
  attendances = db.relationship('Attendance', back_populates = 'email')

@unique
class MigrationStrategy(IntEnum):
  NOT_SET = 0
  DO_NOTHING = 1
  COPY = 2
  MOVE = 3

@unique
class MigrationState(IntEnum):
  NOT_STARTED = 0
  STARTED = 1
  DONE = 2

class Calendar(db.Model):
  """
  The Google calendars we pull from.
  """
  __tablename__ = 'calendars'
  id = db.Column(db.Integer, primary_key = True)
  user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='calendars_user_id_fkey', use_alter=True), nullable = False)
  # Basing length on event uid length.
  gcal_id = db.Column(db.String(1024), nullable = False)
  gcal_summary = db.Column(db.String(100))
  # Extended (from 36) after tokens with length 44 were seen in the wild.
  gcal_sync_token = db.Column(db.String(64), nullable = True)
  gcal_resource_id = db.Column(db.String(36), nullable = True)
  gcal_channel_id = db.Column(db.String(36), nullable = True, unique = True)
  gcal_channel_expires_at = db.Column(db.DateTime, nullable = True)
  gcal_watch_error_count = db.Column(db.Integer, nullable = False, default = 0)
  gcal_watch_last_error = db.Column(db.Text, nullable = True)
  gcal_last_sync_at = db.Column(db.DateTime, nullable = True)
  gcal_sync_log = db.relationship('GcalSyncLog', back_populates = 'calendar')
  created_at = db.Column(db.DateTime, default = datetime.utcnow)
  user = db.relationship('User', foreign_keys=[user_id], back_populates = 'calendars')
  fixed_events = db.relationship('FixedEvent', back_populates = 'calendar')
  db.UniqueConstraint(user_id, gcal_id)
  def is_gcal_primary(self):
    return self.gcal_id == 'primary' or (self.user and self.gcal_id == self.user.email)
  # These record how a calendar was handled during the availability
  # migration. For calendars created after the migration (only), these
  # columns will retain their default values.
  migration_strategy = db.Column(db.Integer, nullable = False, default = MigrationStrategy.NOT_SET)
  migration_state = db.Column(db.Integer, nullable = False, default = MigrationState.NOT_STARTED)

@unique
class EventState(IntEnum):
  UNSCHEDULED = 0
  PENDING = 1
  SCHEDULED = 2
  FINALIZED = 3
  DELETED = 4
  INIT = 5
  PAST = 6

class Event(db.Model):
  """
  A user may make many events.
  """
  __tablename__ = 'events'

  id = db.Column(db.Integer, primary_key = True)
  # stores who created the event
  creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable = False)
  creator = db.relationship('User', back_populates = 'events')
  # length of the meeting (as datetime.timedelta interval)
  length = db.Column(db.Interval, nullable = False)
  tzname = db.Column(db.String(48), nullable=False)
  # the scheduling window for this floating event:
  window_start_local = db.Column(db.DateTime, nullable=False)
  window_end_local = db.Column(db.DateTime, nullable=False)
  window_start = db.Column(db.DateTime) # utc
  window_end = db.Column(db.DateTime) # utc
  # how long (timedelta) before start of meeting to finalize
  freeze_horizon = db.Column(db.Interval, nullable = False)
  # Hides the event from the UI. (While e.g. delete happens async.)
  hidden = db.Column(db.Boolean, nullable = False, default = False)
  state = db.Column(db.Integer, nullable = False, default = EventState.INIT)
  final = db.Column(db.Boolean, nullable = False, default = False)
  # general information
  title = db.Column(db.String(100), nullable = True)
  description = db.Column(db.Text, nullable = True)
  location = db.Column(db.String(1024), nullable = False, default = '') # matches observed max gcal length
  # book keeping
  created_at = db.Column(db.DateTime, default = datetime.utcnow)
  attendances = db.relationship('Attendance', back_populates = 'event')
  # TODO: We should probably drop the `draft` prefixes now that these cols are used for both draft and final meetings.
  # after solver runs it will add draft times, etc.
  draft_start = db.Column(db.DateTime,nullable = True)
  draft_end = db.Column(db.DateTime,nullable = True)
  draft_attendees = db.Column(postgresql.ARRAY(db.Integer), nullable=False, default=[])
  series_id = db.Column(db.Integer, db.ForeignKey('series.id'), nullable = True)
  series = db.relationship('Series', back_populates = 'events')
  dirty = db.Column(db.Boolean, nullable = False, default = True)
  change = db.relationship('Change', back_populates = 'event', uselist=False)

  # 0 = use_new_sync=False, 1 = use_new_sync=True, 2 = new Nx1 sync implementation
  gcal_sync_version = db.Column(db.Integer, nullable=False, default=2)
  # legacy sync
  # gcal_sync_version==0
  draft_events = db.relationship('DraftEvent', back_populates = 'event')

  # gcal_sync_version \in {0,1}
  uid = db.Column(db.String(1024), nullable = True, unique = True)
  # The gcal id of the calendar to which this event was sync'd. (This
  # was a fkey to a `Calendar` when this code was in use. The gcal id
  # was copied here during a subsequent migration.)
  _calendar_id = db.Column(db.Integer)
  gcal_push_id = db.Column(db.String(1024), nullable = True)

  # gcal_sync_version==1
  gcal_sync_state_json = db.Column(db.Text, nullable=False, default='{}')
  gcal_conf_data_json = db.Column(db.Text)
  gcal_create_count = db.Column(db.Integer, nullable = False, default = 0)
  gcal_update_count = db.Column(db.Integer, nullable = False, default = 0)
  gcal_delete_count = db.Column(db.Integer, nullable = False, default = 0)

  def is_init(self):
    return self.state == EventState.INIT

  def is_unscheduled(self):
    return self.state == EventState.UNSCHEDULED

  def is_pending(self):
    return self.state == EventState.PENDING

  def is_scheduled(self):
    return self.state == EventState.SCHEDULED

  def is_past(self):
    return self.state == EventState.PAST

  def is_finalized(self):
    return self.state == EventState.FINALIZED

  def is_deleted(self):
    return self.state == EventState.DELETED

  def is_draft(self):
    return self.is_scheduled() and not self.final

  def is_final(self):
    return self.is_scheduled() and self.final

  def in_progress(self, utcnow=None):
    if utcnow is None:
      utcnow = datetime.utcnow()
    return self.is_scheduled() and self.draft_start <= utcnow

  #TODO: make repair prefs an honest property, with more interesting options. atm it just checks if the event is in a series in which case don't extend the window!
  @property
  def repair_prefs(self):
    return "extend" if self.series_id is None else "no extend"

  @property
  def state_name(self):
    return EventState(self.state).name

  @property
  def draft_unavailable(self):
    return list(set(self.optionalattendees) - set(self.draft_attendees))

  # Helper properties for interfacing with event form
  @property
  def length_in_secs(self):
    return self.length.total_seconds()
  @length_in_secs.setter
  def length_in_secs(self, value):
    self.length = timedelta(seconds=value)

  @property
  def length_in_mins(self):
    return self.length.total_seconds()//60
  @length_in_mins.setter
  def length_in_mins(self, value):
    self.length = timedelta(minutes=value)

  @property
  def freeze_horizon_in_secs(self):
    return self.freeze_horizon.total_seconds()
  @freeze_horizon_in_secs.setter
  def freeze_horizon_in_secs(self, value):
    self.freeze_horizon = timedelta(seconds=value)

  @property
  def freeze_horizon_in_days(self):
    return self.freeze_horizon.days
  @freeze_horizon_in_days.setter
  def freeze_horizon_in_days(self, value):
    self.freeze_horizon = timedelta(days=value)

  @property
  def is_optional(self):
    return True
  @property
  def tz(self):
    return gettz(self.tzname) if self.tzname else None

  @property
  def attendees(self):
    return [a.email.user_id for a in self.attendances
            if not a.deleted and not a.response == AttendeeResponse.NO and a.email.user_id is not None and not a.optional]
  @property
  def optionalattendees(self):
    return [a.email.user_id for a in self.attendances
            if not a.deleted and not a.response == AttendeeResponse.NO and a.email.user_id is not None and a.optional]
  @property
  def invitees(self):
    return [a.email.id for a in self.attendances
            if not a.deleted and a.email.user_id is None and not a.optional]
  @property
  def optionalinvitees(self):
    return [a.email.id for a in self.attendances
            if not a.deleted and a.email.user_id is None and a.optional]
  @property
  def allattendees(self):
    return self.attendees + self.optionalattendees

  @property
  def required_attendee_decline_count(self):
    return len([a for a in self.attendances
                if (not a.deleted and not a.optional and
                    a.response == AttendeeResponse.NO and
                    a.email.user_id is not None)])

  @property
  def optionalattendeepriorities(self):
    return {a.email.user_id : a.normed_priority for a in self.attendances
            if not a.deleted and 
            not a.response == AttendeeResponse.NO and
            a.email.user_id is not None and 
            a.optional}

  @property
  def priority(self):
    #meeting priority is the mean of the z-scored priorities of the attendees
    #first get the z-scored priorities of the attendees
    priorities = [a.normed_priority for a in self.attendances 
                  if not a.deleted and 
                  not a.response == AttendeeResponse.NO and 
                  a.email.user_id is not None and 
                  not a.optional]
    # priorities=[] 
    # for a in self.attendances:
    #   #include prefs of required attendees (not invitees):
    #   if not a.deleted and not a.response == AttendeeResponse.NO and a.email.user_id is not None and not a.optional:
    #     priorities.append(a.normed_priority) 
    #if no required attendees, priority is 50
    if len(priorities)==0:
      return 50
    #return the mean of the normed priorities
    #+10 to make sure there is some benefit to scheduling
    return int(round(10+np.mean(priorities)))

@unique
class AttendeeResponse(IntEnum):
  YES = 0
  NO = 1

@unique
class GcalResponseState(IntEnum):
  ACCEPT = 0 # set response to accepted
  INVITE = 1 # we should send an invite on the next sync
  WAITING = 2 # we're waiting to see a response to an invite

class Attendance(db.Model):
  __tablename__ = 'attendances'
  id = db.Column(db.Integer, primary_key = True)
  event_id = db.Column('event_id', db.ForeignKey('events.id'), nullable=False)
  # We choose to enforce the following: email_id *must* point to
  # either (a) an Email without an associated user (aka an invitee) or
  # (b) the primary email of a User (aka an attendee). (In other
  # words, we don't add aliases directly as attendees.)
  email_id = db.Column('email_id', db.ForeignKey('emails.id'), nullable=False, index=True)
  db.UniqueConstraint(event_id, email_id)
  optional = db.Column(db.Boolean, nullable=False, default=False)
  deleted = db.Column(db.Boolean, nullable=False, default=False)
  response = db.Column(db.Integer, nullable=False, default=AttendeeResponse.YES)
  creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable = False)
  created_at = db.Column(db.DateTime, nullable=False, default = datetime.utcnow)
  event = db.relationship('Event', back_populates = 'attendances')
  email = db.relationship('Email', back_populates = 'attendances')
  creator = db.relationship('User')
  gcal_response_state = db.Column(db.Integer, nullable=False, default=GcalResponseState.ACCEPT) # gcal_sync_version==1
  gcal_uid = db.Column(db.String(64), nullable=True, unique=True) # gcal_sync_version==2
  gcal_hash = db.Column(db.String(32), nullable=True) # gcal_sync_version==2
  _gcal_calendar_id = db.Column(db.Integer) # TODO: drop
  gcal_push_id = db.Column(db.String(1024), nullable = True) # gcaL_sync_version==2
  gcal_create_count = db.Column(db.Integer, nullable = False, default = 0) # gcal_sync_version==2
  gcal_update_count = db.Column(db.Integer, nullable = False, default = 0) # gcal_sync_version==2
  gcal_delete_count = db.Column(db.Integer, nullable = False, default = 0) # gcal_sync_version==2
  #attendence priority is an integer that is used to determine the priority of the event
  # it is [0,100] and 50 is the default
  priority = db.Column(db.Integer, nullable=False, default=50)
  @classmethod
  def default_priority(cls):
    return cls.priority.default.arg
  @property
  def response_name(self):
    return AttendeeResponse(self.response).name
  @property
  def normed_priority(self):
    priority = self.priority
    #get attendence priority of all the user's events
    #TODO cache these stats in the user table so we don't have to do this every time?
    user_attendances = self.email.attendances
    user_attendance_priorities = [a.priority for a in user_attendances]
    mean = np.mean(user_attendance_priorities)
    std = np.std(user_attendance_priorities)
    std = 1 if std < 0.01 else std #avoid divide by zero
    #norm the user's priorities
    #FIXME: there is probably a better way to do this
    zscore_priority = (priority - mean)/(std) 
    #clip at +/- 2 std
    zscore_priority = max(-2, min(2, zscore_priority))
    #scale from [-2, 2] to [0,100]
    normed_priority = (zscore_priority+2)*25 
    return normed_priority

class Series(db.Model):
  __tablename__ = 'series'
  id = db.Column(db.Integer, primary_key = True)
  events = db.relationship('Event', back_populates = 'series')

class DraftEvent(db.Model):
  __tablename__ = 'draft_events'
  id = db.Column(db.Integer, primary_key = True)
  _calendar_id = db.Column(db.Integer, nullable = False) # TODO: drop
  # We originally stored a `calendar_id`, but this was replaced with a
  # `user_id` to allow calendars to be deleted without losing
  # information here. (`calendar_id` always pointed to a particular
  # user's primary calendar, so just storing the `user_id` is
  # sufficient.)
  user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='draft_events_user_id_fkey'), nullable = False)
  event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable = True)
  uid = db.Column(db.String(1024), nullable = False, unique = True)
  event = db.relationship('Event', back_populates = 'draft_events')
  state = db.Column(db.Integer, nullable = False)

  @property
  def state_name(self):
    return DraftEventState(self.state).name

@unique
class DraftEventState(IntEnum):
  INIT = 0
  SYNC = 1
  AWAITING_DELETE = 2
  DONE = 3
  FINALIZING = 4
  FINALIZED_AWAITING_DELETE = 5
  AWAITING_FINAL = 6
  FINALIZED = 7

# Stores a full sync of a Google calendar.
class FixedEvent(db.Model):
  __tablename__ = 'fixed_events'
  id = db.Column(db.Integer, primary_key = True)
  calendar_id = db.Column(db.Integer, db.ForeignKey('calendars.id'), nullable = False)
  calendar = db.relationship('Calendar', back_populates = 'fixed_events')
  uid = db.Column(db.String(1024), nullable = False)
  db.UniqueConstraint(calendar_id, uid)
  # For timed events this is the start / end datetime in utc. For
  # all-day events, this is the start / end datetime in local time.
  # (i.e. The time part is always midnight.)
  start_dt = db.Column(db.DateTime, nullable = False)
  end_dt = db.Column(db.DateTime, nullable = False)
  db.Index('ix_fixed_events_calendar_id_start_dt_end_dt', calendar_id, start_dt, end_dt)
  kron_duty = db.Column(db.Boolean, default = False, nullable = False)
  dirty = db.Column(db.Boolean, nullable = False, default = False, index = True)
  all_day = db.Column(db.Boolean, nullable = False, default = False)
  change = db.relationship('Change', back_populates = 'fixed_event', uselist=False)
  # costs=`None` is represented as NULL in the db, rather than json "null".
  jsoncosts = db.Column(db.Text, nullable = True)
  kind = 'fixed_event'
  @property
  def costs(self):
    return json.loads(self.jsoncosts) if self.jsoncosts else None
  @costs.setter
  def costs(self, val):
    self.jsoncosts = None if val is None else json.dumps(val,default=repr)

  # Properties to compute the start / end time (utc)
  @property
  def start_at(self):
    if self.all_day:
      return to_utc(self.start_dt, self.calendar.user.tz)
    else:
      return self.start_dt
  @property
  def end_at(self):
    if self.all_day:
      return to_utc(self.end_dt, self.calendar.user.tz)
    else:
      return self.end_dt

class SolverLog(db.Model):
  __tablename__ = 'solver_log'
  id = db.Column(db.Integer, primary_key = True)
  created_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
  jsondata = db.Column(db.Text, nullable = False)
  @property
  def data(self):
    #TODO: de-serialize datetime, timedelta, PWlinear etc properly... since we serialize with repr() we can perhaps just eval() the strings?
    return json.loads(self.jsondata)
  @data.setter
  def data(self, val):
    self.jsondata = json.dumps(val,default=repr)

class ErrorLog(db.Model):
  __tablename__ = 'error_log'
  id = db.Column(db.Integer, primary_key = True)
  created_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
  jsondata = db.Column(db.Text, nullable = False)
  @property
  def data(self):
    return json.loads(self.jsondata)
  @data.setter
  def data(self, val):
    self.jsondata = json.dumps(val)

class GcalSyncLog(db.Model):
  __tablename__ = 'gcal_sync_log'
  id = db.Column(db.Integer, primary_key = True)
  calendar_id = db.Column(db.Integer, db.ForeignKey('calendars.id'), nullable = True, index = True)
  calendar = db.relationship('Calendar', back_populates='gcal_sync_log')
  created_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
  full = db.Column(db.Boolean, nullable = False)
  elapsed = db.Column(db.Integer, nullable = False)
  num_items = db.Column(db.Integer, nullable = False)
  num_changes = db.Column(db.Integer, nullable = False)

class Change(db.Model):
  __tablename__ = 'changes'
  id = db.Column(db.Integer, primary_key = True)
  start_at = db.Column(db.DateTime, nullable = False)
  end_at = db.Column(db.DateTime, nullable = False)
  users = db.Column(postgresql.ARRAY(db.Integer), nullable=False, default=[])
  conflict = db.Column(db.Boolean, nullable = False) # space or conflict?
  event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable = True, unique = True)
  event = db.relationship('Event', back_populates = 'change')
  fixed_event_id = db.Column(db.Integer, db.ForeignKey('fixed_events.id'), nullable = True, unique = True)
  fixed_event = db.relationship('FixedEvent', back_populates = 'change')
  created_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)

class LMCache(db.Model):
  cache_key = db.Column(db.String, primary_key=True)
  data = db.Column(db.LargeBinary)
  timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AvailabilityEvent(db.Model):
  __tablename__ = 'availability_events'
  id = db.Column(db.Integer, primary_key = True)
  user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable = False)
  user = db.relationship('User', back_populates = 'availability_events')
  tzname = db.Column(db.String(48), nullable = False)
  start_at = db.Column(db.DateTime, nullable = False)
  end_at = db.Column(db.DateTime, nullable = False)
  recur_end_at = db.Column(db.DateTime, nullable = True)
  cost = db.Column(db.Integer, nullable = False)
  created_at = db.Column(db.DateTime, nullable = False, default = datetime.utcnow)
  db.Index('ix_availability_events_user_id_recur_end_at_start_at', user_id, recur_end_at, start_at)
  @property
  def tz(self):
    return gettz(self.tzname)
