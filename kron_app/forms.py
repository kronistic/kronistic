from datetime import datetime, timedelta
from flask_wtf import FlaskForm
from wtforms import (StringField, TextAreaField, RadioField, IntegerField,
                     BooleanField, DateField, SelectField, HiddenField, SubmitField, FieldList, FormField, IntegerRangeField)
from wtforms import validators
from kron_app.models import User, Attendance
from kron_app.users import find_user_by_email
from kron_app.utils import from_utc, advance_to_midnight

def mins(i):
  return i * 60

def hrs(i):
  return i * 3600

def optint(val):
  if val == 'None':
    return None
  else:
    return int(val)

def advance_to_midnight_if_datetime(d):
  # When rendering the form `d` will either be `None` (new meeting) or
  # a `datetime` (edit meeting). When processing a form submission `d`
  # will be a `date`.
  return advance_to_midnight(d) if type(d) == datetime else d

class AttendeeForm(FlaskForm):
  class Meta:
    csrf = False
  email = HiddenField('email', validators=[validators.Email()], filters=[lambda s: s.strip()])
  optional = BooleanField('optional')

class NewEventForm(FlaskForm):
  """
  Form to make a new event.
  """
  title = StringField('Title', 
    default = 'Important Meeting',
    validators = [validators.DataRequired()])
  description = TextAreaField('Description',
    default = '')
  location = StringField('Location', validators=[validators.Length(max=1024)])
  gmeet = BooleanField('Use Google Meet', default=False)
  # length_in_secs = RadioField('Meeting Length',
  #                             default=mins(30),
  #                             choices = [(mins(15), '15 min'), (mins(30), '30 min'), (mins(60), '1 hour')],
  #                             coerce=int)
  length_in_mins = IntegerField('Meeting Length mins',
                                default=30,
                                validators = [validators.NumberRange(min=15)])

  tzname = HiddenField()
  # The UI can only handle windows that are aligned to day boundaries.
  # Where an existing meeting isn't on such a boundary, we extend the
  # window out to day boundaries when populating the form, such that
  # the old window in included in the new window. (For `window_start`
  # this is just truncation, which we get be default. For window_end
  # we rely on a filter.) This new window will be persisted when the
  # form is submitted.
  window_start_local = DateField('Earliest this meeting can happen',
                                 validators = [validators.DataRequired()])
  window_end_local = DateField('Latest this meeting can happen',
                               filters=[advance_to_midnight_if_datetime],
                               validators = [validators.DataRequired()])

  recur = SelectField('Recur', choices=[(0, 'one-off'), (1, 'recurring')], default=0, coerce=int)
  frequency = SelectField('Freq', choices=[(0, 'day(s)'), (1, 'week(s)'), (2,'month(s)')], default=1, coerce=int)                           
  interval = IntegerField('Every',
                             default=1,
                             validators = [validators.NumberRange(min=1)])    
  repetitions = IntegerField('Repetitions',
                             default=4,
                             validators = [validators.NumberRange(min=1)])                    
  # freeze_horizon_in_secs = RadioField('Freeze Horizon',
  #                                     default=hrs(24),
  #                                     choices = [(hrs(24), '1 day before'), (hrs(48), '2 days before'), (hrs(72), '3 days before')],
  #                                     coerce=int)
  freeze_horizon_in_days = IntegerField('Freeze Horizon', default=1,
                                        validators = [validators.NumberRange(min=1)])
  #priority input is a slider in range 0 to 100
  attpriority = IntegerRangeField('Priority',
                                  default=Attendance.default_priority(),
                                  render_kw=dict(min=0, max=100, step=1),
                                  validators=[validators.NumberRange(min=0, max=100)])
  # priority = SelectField('This meeting is', default='None',
  #                         choices = [('None', 'required'), (1, 'optional'), (10, 'optional (high priority)')], coerce=optint)
  #                       # choices = [('None', 'not optional'), (1, 'optional'), (1, 'optional, medium'), (2, 'opional, high')], coerce=optint)

  # This has an awkward name in order to avoid having this automatically populate Event#attendees.
  theattendees = FieldList(FormField(AttendeeForm))

  submit = SubmitField('Create')
  delete = SubmitField('Delete')

  # When we dynamically add an attendee to the form, we need to
  # generate a unique name for the form element. This determines the
  # id from which it's safe to start generating names. We can't just
  # count the number of attendees because when validation fails it's
  # possible to have attendees on the form with ids greater than the
  # attendee count.
  def next_attendee_id(self):
    # entry names are e.g. `theattendees-0`
    return max((int(entry.name.split('-')[1]) for entry in self.theattendees.entries), default=-1) + 1

  def getname(self, email):
    user = find_user_by_email(email)
    return user.name if user else email

  def set_defaults(self, creator):
    tomorrow = from_utc(datetime.utcnow(), creator.tz).date() + timedelta(days=1)
    if self.window_start_local.data is None:
      self.window_start_local.data = tomorrow
    if self.window_end_local.data is None:
      self.window_end_local.data = tomorrow + timedelta(days=7)

  def validate_window_end_local(self, field):
    if self.window_end_local.data <= self.window_start_local.data:
      raise validators.ValidationError('Latest time must be after earliest time.')

  def validate_theattendees(self, field):
    if len(self.theattendees.data) == 0:
      raise validators.ValidationError('A meeting must have at least one attendee.')


# TODO: Use am/pm as part of #337.
TIME_CHOICES = [(h,'{:d}:00'.format(h)) for h in range(24)]

class SetupForm(FlaskForm):
  start_time = SelectField('Start time', choices=TIME_CHOICES, default='9', coerce=int)
  end_time = SelectField('End time', choices=TIME_CHOICES, default='17', coerce=int)
  mo = BooleanField('Monday', default=True)
  tu = BooleanField('Tuesday', default=True)
  we = BooleanField('Wednesday', default=True)
  th = BooleanField('Thursday', default=True)
  fr = BooleanField('Friday', default=True)
  sa = BooleanField('Saturday', default=False)
  su = BooleanField('Sunday', default=False)
  submit = SubmitField('Submit')

  def all_day_fields(self):
    return [self.mo, self.tu, self.we, self.th, self.fr, self.sa, self.su]

  # It doesn't make sense to attach this validation to any one field.
  # For now, use the submit button. The choice of field is
  # inconsequential given the way errors are rendered.
  def validate_submit(self, field):
    if not any(field.data for field in self.all_day_fields()):
      raise validators.ValidationError('At least one day must be selected.')

  def validate_end_time(self, field):
    if self.end_time.data <= self.start_time.data:
      raise validators.ValidationError('End time must be later than start time.')

  def setup_data(self):
    days = [i for i,d in enumerate('mo tu we th fr sa su'.split()) if self.data[d]]
    return dict(start_time=self.data['start_time'], end_time=self.data['end_time'], days=days)

class MemberForm(FlaskForm):
  class Meta:
    csrf = False
  nick_or_email = HiddenField('Nick or email')

class GroupForm(FlaskForm):
  # group names should have no spaces. use validation that also
  # matches emails to make it easy to find emails or group names in
  # parser...
  nick = StringField('Name', validators = [
    validators.DataRequired(),
    validators.Regexp(r'^[\w.@+-]+$', message="Name can't have spaces or special characters.")])
  members = FieldList(FormField(MemberForm))
  submit = SubmitField('')
  def next_member_id(self):
    return max((int(entry.name.split('-')[1]) for entry in self.members.entries), default=-1) + 1
  def setup(self, taken_nicks):
    self.taken_nicks = taken_nicks
    return self
  def validate_nick(self, field):
    nick = self.nick.data
    nick_lower = nick.lower()
    if nick_lower in ('new', 'everyone'):
      raise validators.ValidationError(f'Name "{nick}" cannot be used.')
    if nick_lower in (n.lower() for n in self.taken_nicks):
      raise validators.ValidationError(f'Name "{nick}" already taken.')
