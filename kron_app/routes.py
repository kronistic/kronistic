import json
from pprint import pformat
from functools import wraps, partial
import pickle
from io import BytesIO
from time import sleep
from flask import (
  flash, render_template, request, redirect, url_for, session, jsonify, abort, Response, send_file, make_response)
from flask_login import current_user, logout_user
from flask_login import login_required as flask_login_required
from flask_login import login_user as flask_login_user
from sqlalchemy import select, or_, desc, func
from sqlalchemy.dialects import postgresql
from kron_app import app
from kron_app import db
from kron_app.models import User, Calendar, Event, EventState, FixedEvent, SolverLog, Email, ErrorLog, Attendance, AttendeeResponse, GcalPushState
from kron_app.events import build_event, build_rrule_series, update_attendee_priority, update_event, build_weekly_series, decline, invited_to, events_for, invitee_to_attendee_fixup, set_attendee_response
from kron_app.changes import record_all_day_event_changes
from kron_app.calendars import delete_calendar as delete_cal
from kron_app.users import find_user_by_email, find_user_by_primary_email, record_sign_up_step, max_sign_up_step, SignUpStep
from kron_app.forms import NewEventForm, SetupForm, GroupForm
from kron_app.gcal_api import get_google_auth, get_google_auth_with_scope, GoogleAuth, get_oauth_session_for_user, GCAL_SCOPES, GCAL_SCOPES_FULL, GCAL_SCOPES_REDUCED
from kron_app.gcal_integration import gcal_chk_for_cal_and_get_timezone, gcal_event_queue_for, gcal_list_calendars
from kron_app.tasks import task_post_signup, task_post_signin, task_post_calendar_notification, task_post_user_notification, task_post_create_events, task_post_modify_event, task_delete_events, task_post_modify_user_timezone, task_post_add_calendar, task_post_delete_calendar, task_post_decline_invite, task_post_add_alias, task_post_modify_groups, task_post_decline_meeting, task_run_solver, task_post_setup, task_enable_push
from kron_app.utils import getstr, ids, tznames, tzoptions, to_utc, from_utc, dotdict, sanitize_url
from kron_app.reasons import impossible_because_users
from kron_app.groups import get_name_and_type, group_members_valid, group_add, group_update, group_delete, unpack_groups, get_deps
from kron_app.availability import api_get_availability, api_set_availability, record_changes, add_core_availability, UNAVAILABLE, EventBitmap
from requests.exceptions import HTTPError
from datetime import datetime, timedelta, time, date

def login_required(f):
  @flask_login_required
  @wraps(f)
  def g(*args, **kwargs):
    if current_user.setup_step is not None and request.endpoint not in ['setup', 'help', 'sign_out']:
      flash('Please complete setup to continue.')
      return redirect(url_for('setup'))
    else:
      return f(*args, **kwargs)
  return g

def admin_required(f):
  @flask_login_required
  @wraps(f)
  def g(*args, **kwargs):
    if not current_user.is_admin:
      abort(403)
    return f(*args, **kwargs)
  return g

@app.after_request
def update_sign_in_state_flag(response):
  key = 'signed_in'
  # A crude way to strip off any sub-domain present in the production
  # hostname. This makes the cookie available from the marketing site.
  domain = '.'.join(app.config['HOSTNAME'].split('.')[-2:]) if app.env == 'production' else None
  if current_user.is_authenticated:
    max_age = int(app.config['PERMANENT_SESSION_LIFETIME'].total_seconds())
    response.set_cookie(key, '1', domain=domain, max_age=max_age, httponly=False)
  else:
    # Setting this on every request is a bit wasteful, but the
    # overhead is probably tolerable for now. (Users won't make very
    # many requests while signed out anyway.)
    response.delete_cookie(key, domain=domain)
  return response

INVITE_UID_KEY = '_'

def login_user(user):
  flask_login_user(user)
  session.permanent = True

@app.route('/')
def index():
  return redirect(url_for('meetings'))

@app.route('/sign_in')
def sign_in():
  if current_user.is_authenticated:
    return redirect(url_for('index'))
  maybe_uid = request.cookies.get('invite_uid')
  record_sign_up_step(maybe_uid, SignUpStep.ACCESS_SIGN_IN_PAGE)
  return render_template('sign_in.html')

@app.route('/auth')
def auth():
  """
  https://requests-oauthlib.readthedocs.io/en/latest/examples/real_world_example.html
  """
  if current_user.is_authenticated:
    return redirect(url_for('index'))

  google = get_google_auth_with_scope()
  auth_url, state = google.authorization_url(
    GoogleAuth.AUTH_URI, 
    access_type = 'offline',
    prompt = 'select_account')
  # state is used to prevent CSRF
  session['oauth_state'] = state
  maybe_uid = request.cookies.get('invite_uid')
  record_sign_up_step(maybe_uid, SignUpStep.GOOGLE_OAUTH_REDIRECT)
  session.pop('next_url', None)
  if 'next' in request.args:
    next_url = sanitize_url(request.args['next'], request.scheme, request.host)
    session['next_url'] = next_url
  return redirect(auth_url)

# Experimenting with re-authorization.
@app.route('/reconsent')
def reconsent():
  # https://developers.google.com/identity/protocols/oauth2/openid-connect#re-consent
  if not current_user.is_authenticated:
    abort(404)

  google = get_google_auth_with_scope()

  # https://developers.google.com/identity/protocols/oauth2/web-server#httprest_8
  #
  # It seems that the only way to give back one scope is to give back everything.
  #
  # access_token = json.loads(current_user.tokens)['access_token']
  # google.post(f'https://oauth2.googleapis.com/revoke?token={access_token}')
  # db.session.commit()

  auth_url, state = google.authorization_url(
    GoogleAuth.AUTH_URI,
    access_type = 'offline',
    prompt = 'consent',
    login_hint = current_user.email)
  session['oauth_state'] = state
  logout_user() # Callback expects this.
  return redirect(auth_url)

@app.route('/gCallback', methods=['GET'])
def callback():
  """
  Callback after Google login.

  1. Check if a user is already logged in, if so redirect.
  2. Check if url has an error query parameter. Handles denied access.
  3. Check if url contains code and state parameters. 
  4. User successfully authenticated app. Create new session.
  """
  # We'll call this on successful sign up / sign in to clear any
  # invite cookie. We don't clear it unconditionally, because a user
  # might not grant calendar access first time through oauth.
  def clear_cookie_and_redirect(url):
    response = make_response(redirect(url))
    response.delete_cookie('invite_uid')
    return response

  maybe_invite_uid = request.cookies.get('invite_uid')
  maybe_next_url = session.pop('next_url', None)

  # redirect user to home page if already logged in
  if current_user is not None and current_user.is_authenticated:
    flash('You are already logged in.')
    return redirect(url_for('index'))

  NO_ACCESS_MSG = ('Kronistic requires access to your calendar to work. '
                   'To continue, please sign in again and tick both permissions boxes when prompted.',
                   'error')
  error_redirect_url = url_for('sign_in')

  if 'error' in request.args:
    record_sign_up_step(maybe_invite_uid, SignUpStep.GOOGLE_OAUTH_CALLBACK_ERROR, request.args['error'])
    if request.args.get('error') == 'access_denied':
      flash(*NO_ACCESS_MSG)
      return redirect(error_redirect_url)

    flash('Error in requesting access to Google.')
    return redirect(error_redirect_url)

  scope = request.args.get('scope', '').split()
  if not set(GCAL_SCOPES).issubset(set(scope)):
    record_sign_up_step(maybe_invite_uid, SignUpStep.GOOGLE_OAUTH_CALLBACK_ERROR, 'missing_scopes')
    flash(*NO_ACCESS_MSG)
    return redirect(error_redirect_url)

  if 'code' not in request.args and 'state' not in request.args:
    flash('Please retry logging in.')
    return redirect(error_redirect_url)
  else:
    # user has successfully authenticated app
    google = get_google_auth(state=session['oauth_state'])

    try:
      token = google.fetch_token(
        GoogleAuth.TOKEN_URI, 
        client_secret = GoogleAuth.CLIENT_SECRET, 
        authorization_response = request.url)
    except HTTPError:
      return 'HTTPError occurred.'

    print(f"refresh_token present: {'refresh_token' in token}")

    google = get_google_auth(token = token)
    resp = google.get(GoogleAuth.USER_INFO)

    if resp.status_code == 200:
      user_data = resp.json()
      email_address = user_data['email'].lower()
      user = find_user_by_primary_email(email_address)

      if user is None: # Sign-up

        email = Email.query.filter_by(address=email_address).one_or_none()
        if email and email.user:
          # Stash the refresh token for potential future use.
          if 'refresh_token' in token:
            email.tokens = json.dumps(token)
            db.session.commit()
          flash(f'You cannot sign in with this account as {email_address} has already been added to another account as an alias.')
          return redirect(error_redirect_url)

        has_cal, tzname = gcal_chk_for_cal_and_get_timezone(google)
        if not has_cal:
          flash('You cannot sign in with this account as it does not have a Google calendar associated with it.')
          return redirect(error_redirect_url)

        # It's possible we won't get a refresh token here, which is
        # bad. (Here we set it to a dummy value, only to avoid null
        # handling through-out the app.)

        # Known causes of not getting a refresh token:

        # A previous sign-up was declined because no invite was
        # present. (No longer happens, but it did.)

        # A user sign-up was declined because the user didn't have a
        # calendar, but they subsequently obtained a calendar then
        # signed up successfully.

        # A small number of zombie accounts (and their refresh tokens)
        # were removed as part of #455.

        if 'refresh_token' not in token:
          token['refresh_token'] = 'none'
        assert 'refresh_token' in token

        user = User()
        user.primary_email = email or Email(address=email_address)
        user.name = getstr(user_data, 'name')
        user.first_name = getstr(user_data, 'given_name')
        user.last_name = getstr(user_data, 'family_name')
        user.tokens = json.dumps(token)
        user.last_login_at = datetime.utcnow()
        user.is_admin = User.query.count() == 0
        if tzname:
          user.tzname = tzname
        db.session.add(user)
        db.session.commit()

        # Do this immediately so that any invited to meetings are
        # visible.
        tosync = invitee_to_attendee_fixup(user, user.primary_email)

        # Check for case where user has an invite for an email other
        # than the one associated with their google account:
        if maybe_invite_uid:
          invite_email = Email.query.filter_by(uid=maybe_invite_uid).one_or_none()
          if invite_email and not invite_email.user: # Skip if already taken, inc. by `user`.
            tosync += invitee_to_attendee_fixup(user, invite_email)
            invite_email.user = user
            db.session.commit()

        # Run (async.) post sign-up tasks for user.
        task_post_signup.delay(user.id, tosync)

        login_user(user)
        return clear_cookie_and_redirect(url_for('setup'))

      else: # Sign-in

        # Preserve existing refresh token if we didn't get a new one.
        # In production we've seen `prompt=select_account` sometimes
        # not include a refresh token.
        if 'refresh_token' not in token:
          # The old refresh token is guaranteed to exist, since we
          # always have one at sign-up (even if its 'none'), and then
          # preserve it (here) at subsequent logins.
          oldtoken = json.loads(user.tokens)
          token['refresh_token'] = oldtoken['refresh_token']
        assert 'refresh_token' in token

        user.name = getstr(user_data, 'name')
        user.first_name = getstr(user_data, 'given_name')
        user.last_name = getstr(user_data, 'family_name')
        user.tokens = json.dumps(token)
        user.last_login_at = datetime.utcnow()
        db.session.add(user)
        db.session.commit()

        task_post_signin.delay(user.id)

        login_user(user)
        next_url = url_for('alias', **{INVITE_UID_KEY: maybe_invite_uid}) if maybe_invite_uid else (maybe_next_url or url_for('meetings'))
        return clear_cookie_and_redirect(next_url)

    flash('Failed to fetch data from Google.')
    return redirect(error_redirect_url)

@app.route('/sign_out')
@login_required
def sign_out():
  logout_user()
  return redirect(url_for('sign_in'))

@app.route('/profile')
@login_required
def profile():
  calendars = sorted(current_user.calendars, key=lambda c: -1 if c.is_gcal_primary() else c.id)
  groups = current_user.groups
  expanded_groups = sorted((nick, [get_name_and_type(nick_or_email, groups) for nick_or_email in members])
                           for (nick, members) in groups.items())
  unpacked = dict((nick ,list(unpack_groups(nick, groups))) for nick in groups.keys())
  return render_template('profile.html',
                         user=current_user, calendars=calendars, tzoptions=tzoptions(),
                         expanded_groups=expanded_groups, groups=groups, unpacked=unpacked)

@app.route('/meetings')
@login_required
def meetings():
  def default_memo():
    threshold = timedelta(minutes=5) if app.config['ENV'] == 'development' else timedelta(days=7)
    account_age = datetime.utcnow()-current_user.created_at
    did_setup = current_user.setup_data is not None
    return 'welcome' if account_age<threshold and did_setup else 'greeting'
  allevents = events_for(current_user).order_by('id').all()
  init = [e for e in allevents if e.is_init()]
  scheduled = sorted([e for e in allevents if e.is_scheduled()], key=lambda e: e.draft_start)
  others = [e for e in allevents if not (e.is_scheduled() or e.is_init())]
  main = init + scheduled
  memo = request.args.get('memo', default_memo())
  return render_template('meetings.html', main=main, others=others, event_count=len(allevents), memo=memo)

def attendee(attendance):
  email = attendance.email.address
  return dict(email=email,
              name=attendance.email.user.name if attendance.email.user else email,
              optional=attendance.optional)

@app.route('/groups/new', methods=['GET', 'POST'])
@login_required
def add_group():
  groups = current_user.groups
  group = dotdict(nick='', members=[])
  form = GroupForm(obj=group).setup(taken_nicks=groups.keys())
  if form.validate_on_submit():
    members = [m['nick_or_email'] for m in form.members.data]
    # Additional validation of members not performed by form. It's OK
    # to do this here because the auto-complete ordinarily ensures
    # only valid users and groups are entered.
    if not group_members_valid(groups, members):
      raise Exception('invalid group members')
    nick = form.nick.data
    current_user.groups = group_add(groups, nick, members)
    db.session.commit()
    flash('Group added!')
    task_post_modify_groups.delay(current_user.id, [nick])
    return redirect(url_for('profile'))
  else:
    return render_template('group.html', update=False,
                           autocomplete_options = autocomplete_options_for(current_user),
                           form=form, group=group,
                           get_name_and_type=partial(get_name_and_type, groups=groups))

@app.route('/groups/<nick>', methods=['GET', 'POST'])
@login_required
def edit_group(nick):
  groups = current_user.groups
  if nick not in groups:
    flash('Group not found.')
    return redirect(url_for('profile'))
  group = dotdict(nick=nick, members=[dotdict(nick_or_email=nick_or_email) for nick_or_email in groups[nick]])
  form = GroupForm(obj=group).setup(taken_nicks=(n for n in groups.keys() if n!=nick))
  if form.validate_on_submit():
    members = [m['nick_or_email'] for m in form.members.data]
    if not group_members_valid(groups, members):
      raise Exception('invalid group members')
    newnick = form.nick.data
    names = {newnick} | get_deps(nick, groups)
    current_user.groups = group_update(groups, nick, newnick, members)
    db.session.commit()
    flash('Group updated!')
    # TODO: Skip when nothing has changed?
    task_post_modify_groups.delay(current_user.id, list(names))
    return redirect(url_for('profile'))
  else:
    return render_template('group.html', update=True,
                           autocomplete_options = autocomplete_options_for(current_user),
                           form=form, group=group,
                           get_name_and_type=partial(get_name_and_type, groups=groups))

@app.route('/groups/<nick>/delete', methods=['POST'])
@login_required
def delete_group(nick):
  groups = current_user.groups
  if nick not in groups:
    flash('Group not found.')
    return redirect(url_for('profile'))
  names = get_deps(nick, groups)
  current_user.groups = group_delete(groups, nick)
  db.session.commit()
  flash('Group deleted!')
  task_post_modify_groups.delay(current_user.id, list(names))
  return redirect(url_for('profile'))

def autocomplete_options_for(user):
  opts = [dict(name=u.name, email=u.email, type='user') for u in [user]+user.contacts]
  groups = user.groups
  for nick in groups.keys():
    members = []
    for email in unpack_groups(nick, groups):
      u = find_user_by_email(email)
      # TODO: This is written this way to handle any existing groups
      # that are populated with emails of non kron users. By the time
      # we put this live, it will be the case that adding such emails
      # to a group is not possible. We need to check any groups before
      # changing this though.
      member = dict(name=u.name, email=u.email) if u else dict(name=email, email=email)
      members.append(member)
    opts.append(dict(name=nick, members=members, type='group'))
  return opts

@app.route('/meetings/new', methods=['GET', 'POST'])
@login_required
def add_meeting():
  theattendees = [dict(email=current_user.email, name=current_user.name, optional=False)]
  title = f"Meeting with {current_user.first_name}"
  form = NewEventForm(theattendees = theattendees, tzname=current_user.tzname, title=title)
  form.set_defaults(current_user)
  if form.validate_on_submit():
    event_data = dict(creator = current_user,
                      length_in_mins = form.length_in_mins.data,
                      tzname = form.tzname.data,
                      window_start_local = datetime.combine(form.window_start_local.data, time()),
                      window_end_local = datetime.combine(form.window_end_local.data, time()),
                      freeze_horizon_in_days = form.freeze_horizon_in_days.data,
                      title = form.title.data,
                      description = form.description.data,
                      location = form.location.data,
                      theattendees = form.theattendees.data)
    if form.recur.data == 0:
      events = [build_event(**event_data)]
    else:
      freqs={0:'DAILY',1:"WEEKLY",2:"MONTHLY"}
      freq=freqs[form.frequency.data]
      rrule=f"FREQ={freq};INTERVAL={form.interval.data};COUNT={form.repetitions.data}"
      events = build_rrule_series(event_data, rrule).events
      # events = build_weekly_series(event_data, form.repetitions.data).events
    #set attendee priority
    for e in events:
      update_attendee_priority(e, current_user.id, form.attpriority.data)
    db.session.commit()
    assert len(events) > 0
    event = events[0]
    new_attendees = list(set(event.attendees+event.optionalattendees)-{current_user.id})
    new_invitees = event.invitees+event.optionalinvitees
    task_post_create_events.delay(ids(events), new_attendees, new_invitees,
                                  run_solver=not all(e.is_pending() for e in events))
    flash('Meeting created!')
    return redirect('/meetings')
  return render_template('event.html',
                         form = form, creator = current_user,
                         autocomplete_options = autocomplete_options_for(current_user),
                         declined_by = [], update = False)

@app.route('/api/user', methods=['GET'])
@login_required
def api_user():
  email = request.args.get('email', '').lower()
  user = find_user_by_email(email)
  if not user:
    abort(404)
  return jsonify({'name': user.name, 'email': user.email})

@app.route('/meeting/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_meeting(id):
  event = Event.query.filter(Event.state != EventState.DELETED) \
                     .filter_by(hidden=False, id=id) \
                     .one_or_none()
  if event is None:
    flash('Meeting not found.')
    return redirect('/meetings')
  if event.is_finalized() or event.is_past(): # old style finalized or past
    flash('This meeting can no longer be edited.')
    return redirect('/meetings')
  editor_ids = [event.creator_id] + event.allattendees
  if current_user.id not in editor_ids:
    flash('Access denied.')
    return redirect('/meetings')
  def sortkey(a):
    return (a.email.user != event.creator, (1, a.email.address) if a.email.user is None else (0, a.email.user.name))
  theattendees = [attendee(a) for a in sorted((a for a in event.attendances if not a.deleted), key=sortkey)]
  declined_by = [a.email.address for a in event.attendances if a.response == AttendeeResponse.NO]
  #get the priority of this event for the current user
  attpriority = next((a.priority for a in event.attendances if a.email.user_id == current_user.id), Attendance.default_priority())
  form = NewEventForm(obj = event, theattendees = theattendees, attpriority=attpriority)
  form.submit.label.text = 'Update'
  if form.validate_on_submit():
    made_pending, new_attendees, new_invitees = update_event(event,
                                                             length_in_mins = form.length_in_mins.data,
                                                             tzname = form.tzname.data,
                                                             window_start_local = datetime.combine(form.window_start_local.data, time()),
                                                             window_end_local = datetime.combine(form.window_end_local.data, time()),
                                                             freeze_horizon_in_days = form.freeze_horizon_in_days.data,
                                                             title = form.title.data,
                                                             description = form.description.data,
                                                             location = form.location.data,
                                                             theattendees = form.theattendees.data)
    #update priority of this event for the current user
    update_attendee_priority(event, current_user.id, form.attpriority.data)
    db.session.commit()
    task_post_modify_event.delay(event.id, new_attendees, new_invitees, made_pending)
    flash('Meeting updated!')
    return redirect('/meetings')
  return render_template('event.html',
                         form = form, creator = event.creator,
                         autocomplete_options = autocomplete_options_for(current_user),
                         update = True,
                         event = event, declined_by = declined_by)

@app.route('/meetings/delete', methods=['POST'])
@login_required
def delete_meeting():
  event_id = int(request.form['event_id'])
  event = Event.query.filter(Event.state != EventState.FINALIZED,
                             Event.state != EventState.DELETED,
                             Event.state != EventState.PAST) \
                     .filter_by(creator=current_user,
                                hidden=False,
                                id=event_id).one_or_none()
  if event is None:
    flash('Meeting not found.')
    return redirect('/meetings')
  if request.form['all']:
    events = Event.query.filter(Event.state != EventState.FINALIZED,
                                Event.state != EventState.DELETED,
                                Event.state != EventState.PAST) \
                        .filter_by(series_id=event.series_id).all()
    db.session.delete(event.series)
  else:
    events = [event]
  for event in events:
      event.hidden = True
  db.session.commit()
  task_delete_events.delay(ids(events))
  flash('Meeting(s) deleted!')
  return redirect(url_for('meetings'))

@app.route('/meetings/decline', methods=['POST'])
@login_required
def decline_meeting():
  event_id = int(request.form['event_id'])
  event = events_for(current_user).filter(Event.id==event_id).one_or_none()
  if event is None:
    flash('Meeting not found.')
    return redirect('/meetings')
  if request.form['all']:
    events = events_for(current_user).filter(Event.series==event.series).all()
  else:
    events = [event]
  send_notification = False
  for e in events:
    set_attendee_response(e, current_user, AttendeeResponse.NO)
    attendance = next(a for a in e.attendances if a.email.user == current_user)
    send_notification |= (not attendance.optional)
  db.session.commit()
  task_post_decline_meeting.delay(current_user.id, ids(events), send_notification)
  flash('Meeting(s) declined!')
  return redirect(url_for('meetings'))

@app.route('/meeting/<int:id>/fixit', methods=['GET'])
@login_required
def fix_meeting(id):
  event = Event.query.filter(Event.state != EventState.FINALIZED,
                             Event.state != EventState.DELETED,
                             Event.state != EventState.PAST) \
                     .filter_by(hidden=False, id=id) \
                     .one_or_none()
  if event is None:
    flash('Meeting not found.')
    return redirect('/meetings')
  editor_ids = [event.creator_id] + event.allattendees
  if current_user.id not in editor_ids:
    flash('Access denied.')
    return redirect('/meetings')
  # TODO: Less verbose date ranges. (e.g. Avoid repeating month and
  # year where possible. e.g. Thur 2 - Fri 3 Sept 20XX. Drop year
  # where unambiguous as we do elsewhere.) Use existing library for
  # this?
  window_start_local = (event.window_start_local).strftime('%a, %B %-d, %Y')
  window_end_local = (event.window_end_local-timedelta(days=1)).strftime('%a, %B %-d, %Y')
  possible, reason_sets, reason_singles = impossible_because_users(event)
  reason_sets = [r for r in reason_sets if len(r)>1]
  reason_sets = [[User.query.get(int(id)) for id in reason] for reason in reason_sets]
  reason_singles = [(User.query.get(int(id)),k) for id,k in reason_singles]
  return render_template('fixit.html', event=event,
                         impossible=not possible, reason_sets=reason_sets, reason_singles=reason_singles,
                         window_start_local=window_start_local, window_end_local=window_end_local)

@app.route('/decline/<uid>', methods=['GET'])
def decline_redirect(uid):
  return redirect(url_for('invite', **{INVITE_UID_KEY: uid}), 301)

@app.route('/invite', methods=['GET'])
def invite():
  uid = request.args.get(INVITE_UID_KEY)
  if current_user.is_authenticated:
    return redirect(url_for('alias', **{INVITE_UID_KEY: uid}))
  email = uid and Email.query.filter_by(uid=uid).one_or_none()
  if not email:
    abort(404)
  if email.user:
    flash('You have already created your account.')
    return redirect(url_for('sign_in'))
  record_sign_up_step(email, SignUpStep.ACCESS_INVITE_PAGE)
  # Invited-to events that have not been declined already.
  event_ids = set(ids(invited_to(email))) - set(email.declined)
  events = Event.query.filter(Event.id.in_(event_ids)).all()
  creator_names = list(set(e.creator.name for e in events))
  # Don't show dupes, most likely created by series.
  uniq_events = list(set((e.title, e.creator.name) for e in events))
  response = make_response(render_template('invite.html', email=email, events=uniq_events, creator_names=creator_names))
  # Stash the invite uid in a cookie so that we can match a new user
  # with their invite post sign-up.
  response.set_cookie('invite_uid', uid, max_age=3600)
  return response

@app.route('/decline/<email_uid>', methods=['POST'])
def do_decline(email_uid):
  # If we're very unlucky, this could decline events we didn't mention
  # on the confirm screen. If we stick with this approach long-term,
  # we might want to include information about which events we asked
  # the user about in the form, and then decline only those here.
  email = Email.query.filter_by(user_id=None,uid=email_uid).one_or_none()
  if email is not None:
    users_to_notify = decline(email)
    task_post_decline_invite.delay(email.id, ids(users_to_notify))
  flash('Thank you. We will let the organizer know.')
  return redirect(url_for('invite', **{INVITE_UID_KEY: email_uid}))

@app.route('/alias', methods=['GET','POST'])
def alias():
  uid = request.args.get(INVITE_UID_KEY)
  if not current_user.is_authenticated:
    flash(app.login_manager.login_message)
    response = make_response(redirect(url_for(app.login_manager.login_view)))
    if uid:
      response.set_cookie('invite_uid', uid, max_age=3600)
    return response
  email = uid and Email.query.filter_by(uid=uid).one_or_none()
  if not email:
    abort(404)
  if email.user:
    if email.user == current_user:
      flash('This email is already associated with your account.')
    else:
      flash('This email is taken by another account.')
    return redirect(url_for('profile'))
  if request.method == 'POST':
    tosync = invitee_to_attendee_fixup(current_user, email)
    current_user.emails.append(email)
    db.session.commit()
    task_post_add_alias.delay(tosync)
    flash('Alias added!')
    return redirect(url_for('meetings'))
  # Don't show the meetings the user is already attending or has already declined.
  declined_ids = set(a.event_id for a in Attendance.query.filter_by(email=current_user.primary_email, response=AttendeeResponse.NO).all())
  event_ids = set(ids(invited_to(email))) - set(ids(events_for(current_user).all())) - declined_ids
  events = Event.query.filter(Event.id.in_(event_ids)).all()
  uniq_events = list(set((e.title, e.creator.name) for e in events))
  return render_template('alias.html', email=email, events=uniq_events)

@app.route('/calendar/new', methods=['GET'])
@login_required
def add_calendar():
  gcal_ids = [current_user.email if c.is_gcal_primary() else c.gcal_id for c in current_user.calendars]
  google = get_oauth_session_for_user(current_user)
  items, result = gcal_list_calendars(current_user, show_hidden=True)
  if result == 'error':
    flash('Failed to fetch calendar list.')
    return redirect(url_for('profile'))
  items = [item for item in items if not item['id'] in gcal_ids]
  return render_template('calendar.html', items=items)

@app.route('/calendars', methods=['POST'])
@login_required
def do_add_calendar():
  gcal_id = request.form.get('gcal_id')
  if not gcal_id:
    flash('Please choose a calendar.')
    return redirect(url_for('add_calendar'))
  gcal_summary = request.form[gcal_id][:100]
  calendar = Calendar(user=current_user,gcal_id=gcal_id,gcal_summary=gcal_summary)
  db.session.add(calendar)
  db.session.commit()
  task_post_add_calendar.delay(calendar.id)
  flash('Calendar added!')
  return redirect(url_for('profile'))

@app.route('/calendar/delete', methods=['POST'])
@login_required
def delete_calendar():
  calendar_id = request.form['calendar_id']
  calendar = Calendar.query.filter_by(user=current_user,id=calendar_id).one_or_none()
  if calendar is None:
    flash('Calendar not found.')
    return redirect(url_for('profile'))
  gcal_resource_id = calendar.gcal_resource_id
  gcal_channel_id = calendar.gcal_channel_id
  delete_cal(calendar)
  db.session.commit()
  task_post_delete_calendar.delay(calendar.user_id, gcal_channel_id, gcal_resource_id)
  flash('Calendar removed!')
  return redirect(url_for('profile'))

@app.route('/enable_push', methods=['POST'])
@login_required
def enable_push():
  assert current_user.gcal_push_state == GcalPushState.OFF
  current_user.gcal_push_state = GcalPushState.CREATING
  db.session.commit()
  task_enable_push.delay(current_user.id)
  flash('Meeting sync is now enabled.')
  return redirect(url_for('profile'))

@app.route('/profile/preferences', methods=['POST'])
@login_required
def profile_preferences():
  current_user.send_new_meeting_notifications = bool(request.form['meeting_notifications'])
  current_user.send_freeze_notifications = bool(request.form['freeze_notifications'])
  # current_user.poems = bool(request.form['poems'])
  current_user.virtual_link = request.form['virtual_link']
  tzname = request.form.get('tzname')
  old_tzname = current_user.tzname
  new_tzname = tzname if tzname in tznames() else old_tzname
  tzname_changed = new_tzname != old_tzname
  if tzname_changed:
    record_all_day_event_changes(current_user)
  # Update timezone.
  current_user.tzname = new_tzname
  db.session.commit()
  if tzname_changed:
    task_post_modify_user_timezone.delay()
  flash('Preferences updated.')
  return redirect(url_for('profile'))

@app.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
  if current_user.setup_step is None:
    # admin users can re-enter (but not until initial set-up is
    # complete)
    if current_user.is_admin and current_user.setup_complete:
      current_user.setup_step = 0
      db.session.commit()
    else:
      flash('Your account is already setup.')
      return redirect(url_for('meetings'))

  form = SetupForm()
  if form.validate_on_submit():
    setup_data = form.setup_data()
    current_user.setup_json = json.dumps(setup_data)
    current_user.setup_step = None # We're done
    if not current_user.setup_complete: # don't add availability when an admin user re-enters
      add_core_availability(current_user, **setup_data)
    db.session.commit()
    task_post_setup.delay(current_user.id)
    return redirect(url_for('meetings'))
  else:
    return render_template('setup.html', form=form)

@app.route('/availability')
@login_required
def availability():
  return render_template('availability.html', UNAVAILABLE=UNAVAILABLE, EventBitmap=EventBitmap)

@app.route('/api/availability/<datestr>', methods=['GET'])
@login_required
def get_availability(datestr):
  if app.env == 'development':
    sleep(0.2)
  d = date.fromisoformat(datestr)
  user = User.query.get(request.args['user_id']) if current_user.is_admin and ('user_id' in request.args) else current_user
  assert user
  availability, events, meetings = api_get_availability(user, d)
  return jsonify({'date': datestr, 'availability': availability, 'events': events, 'meetings': meetings})

@app.route('/api/availability', methods=['POST'])
@login_required
def update_availability():
  if app.env == 'development':
    sleep(0.2)
  json = request.get_json()
  d = date.fromisoformat(json['date'])
  api_set_availability(current_user, d, json['availability'], json['recur'])
  task_run_solver.delay()
  return 'ok'

# Simulate sync:
# curl -k -H "X-Goog-Resource-State: sync" -X POST https://localhost:8080/gcal_webhook
@app.route('/gcal_webhook', methods=['POST'])
@app.route('/gcal_events_webhook', methods=['POST'])
def gcal_events_webhook():
  state = request.headers.get('X-Goog-Resource-State')
  if state == 'sync':
    # Handle the "sync" message sent after subscribing to a
    # calendar by doing nothing other than return http 200.
    # https://developers.google.com/calendar/api/guides/push#sync-message
    return 'ok'
  elif state == 'exists':
    # Receive notification of a change.
    channel_id = request.headers['X-Goog-Channel-ID']
    resource_uri = request.headers['X-Goog-Resource-Uri']
    if resource_uri.startswith('https://www.googleapis.com/calendar/v3/calendars'):
      calendar = Calendar.query.filter_by(gcal_channel_id=channel_id).one_or_none()
      if calendar:
        task_post_calendar_notification.delay(calendar.id)
    elif resource_uri.startswith('https://www.googleapis.com/calendar/v3/users/me/calendarList'):
      user = User.query.filter_by(gcal_channel_id=channel_id).one_or_none()
      if user:
        task_post_user_notification.delay(user.id)
    else:
      raise Exception(f'unknown resource_uri: {resource_uri}')
    return 'ok'
  else:
    # Unrecognised call to end point
    return 'error', 500

@app.route('/admin/users', methods=['GET'], defaults=dict(show='all'))
@app.route('/admin/users/<show>', methods=['GET'])
@admin_required
def users(show):
  assert show in ('all', 'recent')
  def event_counts(user):
    events = events_for(user).all()
    queue = gcal_event_queue_for(user.id) if user.gcal_quota == 0 else []
    pending_gcal_creation = len(queue)
    next_event_to_create =  queue[0] if queue else None
    return len(events), len([e for e in events if e.creator == user]), pending_gcal_creation, next_event_to_create
  def extra_info(user):
    notification_status = ('off' if user.gcal_channel_expires_at is None
                           else 'expired' if user.gcal_channel_expires_at < datetime.utcnow()
                           else 'ok')
    scope = set(json.loads(user.tokens).get('scope', []))
    has_full_scopes = set(GCAL_SCOPES_FULL).issubset(scope)
    has_reduced_scopes = set(GCAL_SCOPES_REDUCED).issubset(scope)
    scope_status = ('full' if (has_full_scopes and not has_reduced_scopes) else
                    'reduced' if (has_reduced_scopes and not has_full_scopes) else
                    'other')
    return notification_status, scope_status
  q = User.query
  q = q.order_by('id') if show == 'all' else q.order_by(desc('id')).limit(20)
  users = q.all()
  users_extra = [(u, *event_counts(u), *extra_info(u)) for u in users]
  admin_count = User.query.filter_by(is_admin=True).count()
  return render_template('users.html', users_extra=users_extra, admin_count=admin_count, show=show)

@app.route('/admin', methods=['GET'])
@admin_required
def events():
  def count(state):
    return Event.query.filter(Event.state==state).count()
  counts = dict((state.name, count(state)) for state in EventState)
  def get_top_creators(period=None):
    q = db.session.query(Event.creator_id,func.count(Event.creator_id)) \
                  .filter(Event.state!=EventState.DELETED) \
                  .group_by(Event.creator_id) \
                  .order_by(desc(func.count(Event.creator_id)),'creator_id')
    if period:
      q = q.filter(Event.created_at > (datetime.utcnow() - period))
    return [(User.query.get(user_id), count) for user_id, count in q.limit(10).all()]
  return render_template('events.html', counts=counts,
                         top_creators_all_time=get_top_creators(),
                         top_creators_last_7_days=get_top_creators(timedelta(days=7)))

@app.route('/admin/calendars', methods=['GET'])
@admin_required
def calendars():
  calendars = Calendar.query.order_by('id').all()
  return render_template('calendars.html', calendars=calendars, utcnow=datetime.utcnow())

PAGE_SIZE = 20

@app.route('/admin/solver', methods=['GET'])
@admin_required
def solver():
  page = max(0, int(request.args.get('page', 0)))
  entries = SolverLog.query.order_by(desc('created_at')).offset(page*PAGE_SIZE).limit(PAGE_SIZE).all()
  count = SolverLog.query.count()
  show_prev = page > 0
  show_next = (page+1) * PAGE_SIZE < count
  return render_template('solver.html', entries=entries, count=count, page=page, show_prev=show_prev, show_next=show_next)

@app.route('/admin/solver.pickle', methods=['GET'])
@admin_required
def solver_pickle():
  page = max(0, int(request.args.get('page', 0)))
  entries = SolverLog.query.order_by(desc('created_at')).offset(page*PAGE_SIZE).limit(PAGE_SIZE).all()
  entries = [e.data for e in entries]
  stream = BytesIO()
  pickle.dump(entries, stream, pickle.HIGHEST_PROTOCOL)
  # for entry in entries:
  #   pickle.dump(entry, stream, pickle.HIGHEST_PROTOCOL)
  stream.seek(0)
  return send_file(stream, cache_timeout=0, as_attachment=True, attachment_filename='solver.pickle')

@app.route('/admin/solver/<int:id>', methods=['GET'])
@admin_required
def solver_log_entry(id):
  entry = SolverLog.query.get(id)
  if not entry:
    flash('Entry not found.')
    return redirect(url_for('solver'))
  return Response(pformat(entry.data), mimetype='text/plain')

@app.route('/admin/errors', methods=['GET'])
@admin_required
def errors():
  entries = ErrorLog.query.order_by(desc('created_at')).limit(20).all()
  return render_template('errors.html', entries=entries)

@app.route('/admin/errors/<int:id>/tb', methods=['GET'])
@admin_required
def tb(id):
  entry = ErrorLog.query.get(id)
  return Response(entry.data['tb'], mimetype='text/plain')

@app.route('/test_error')
def test_error():
  raise Exception('test error')

@app.route('/meeting/<int:id>/info', methods=['GET'])
@admin_required
def event_info(id):
  event = Event.query.get(id)
  if event is None:
    return abort(404)
  props = ['state_name', 'final', 'hidden', 'series_id', 'creator_id',
           'length', 'freeze_horizon', 'window_start', 'window_end',
           'attendees', 'optionalattendees', 'invitees', 'optionalinvitees',
           'draft_start', 'draft_end', 'draft_attendees', 'gcal_sync_version']
  event_data = [(p, getattr(event,p)) for p in props]
  return render_template('info.html', event_data=event_data)

@app.route('/admin/invites', methods=['GET'])
@admin_required
def invites():
  emails = Email.query.filter_by(user=None).order_by('address').all()
  invites = [(email, ids(invited_to(email)), max_sign_up_step(email)) for email in emails]
  return render_template('invites.html', invites=invites, INVITE_UID_KEY=INVITE_UID_KEY)

@app.route('/admin/queue', methods=['GET'])
@admin_required
def queue():
  def parse(p):
    headers = json.loads(p)['headers']
    return headers['task'], headers['argsrepr'], headers['kwargsrepr']
  ps = db.session.execute('SELECT payload FROM kombu_message WHERE visible=true ORDER BY id;').scalars().all()
  q = (parse(p) for p in ps)
  return render_template('queue.html', q=q)
