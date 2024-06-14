import os
import json
import time
from uuid import uuid4
import urllib.parse
from requests_oauthlib import OAuth2Session
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError
from kron_app import app, db
from kron_app.models import User, Calendar

# This UID was generated specifically for the open source release.
GCAL_EVENT_UID_PREFIX = '690c3d3ed196469888edb48df1d7600b'

GCAL_SCOPES_FULL = ['https://www.googleapis.com/auth/calendar']
GCAL_SCOPES_REDUCED = ['https://www.googleapis.com/auth/calendar.app.created',
                       'https://www.googleapis.com/auth/calendar.readonly']
GCAL_SCOPES = GCAL_SCOPES_REDUCED

class GoogleAuth:
  CLIENT_ID = os.environ.get('KRON_GOOGLE_OAUTH2_ID')
  CLIENT_SECRET = os.environ.get('KRON_GOOGLE_OAUTH2_SECRET')
  REDIRECT_PATH = 'gCallback'
  AUTH_URI = 'https://accounts.google.com/o/oauth2/v2/auth'
  TOKEN_URI = 'https://www.googleapis.com/oauth2/v4/token'
  USER_INFO = 'https://www.googleapis.com/userinfo/v2/me'
  SCOPE = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
  ] + GCAL_SCOPES

HOSTNAME = app.config['HOSTNAME']
REDIRECT_URI = f'https://{HOSTNAME}/{GoogleAuth.REDIRECT_PATH}'

def get_google_auth(state = None, token = None):
  # This does in fact hold. This has always been odd method -- it
  # might be better split into `get_google_auth_from_state` and
  # `get_google_auth_from_token`.
  assert (state is not None) ^ (token is not None)
  if token:
    return OAuth2Session(GoogleAuth.CLIENT_ID, token = token)
  if state:
    return OAuth2Session(
      GoogleAuth.CLIENT_ID,
      state = state,
      redirect_uri = REDIRECT_URI)

def get_google_auth_with_scope():
  return OAuth2Session(GoogleAuth.CLIENT_ID, redirect_uri=REDIRECT_URI, scope=GoogleAuth.SCOPE)

GCAL_CALENDARS_URI = 'https://www.googleapis.com/calendar/v3/calendars'
GCAL_CALENDAR_LIST_URI = 'https://www.googleapis.com/calendar/v3/users/me/calendarList'
GCAL_SETTINGS_URI = "https://www.googleapis.com/calendar/v3/users/me/settings"

def gcal_calendar_uri(gcal_id):
  assert type(gcal_id) == str
  gid = urllib.parse.quote(gcal_id)
  return f'{GCAL_CALENDARS_URI}/{gid}'

def gcal_calendar_list_uri(gcal_id):
  assert type(gcal_id) == str
  gid = urllib.parse.quote(gcal_id)
  return f'{GCAL_CALENDAR_LIST_URI}/{gid}'

def gcal_events_uri(gcal_id):
  calendar_uri = gcal_calendar_uri(gcal_id)
  return f'{calendar_uri}/events'



# A wrapper around `requests_oauthlib.OAuth2Session` that adds basic
# handling / logging of api access errors. Instances are typically
# created with `get_oauth_session_for_user`.
class OAuthSession:

  def __init__(self, oauthsession, user):
    self.oauthsession = oauthsession
    self.user = user

  def _with_error_handling(self, method, *args, **kwargs):
    try:
      resp = getattr(self.oauthsession, method)(*args, **kwargs)
    except InvalidGrantError:
      self._inc_count()
      return
    if resp.status_code == 401: # invalid credentials
      self._inc_count()
      return
    elif resp.status_code == 403 and 'quotaExceeded' in resp.text:
      self.user.gcal_sync_enabled = False
      db.session.commit()
      raise Exception('gcal api quota exceeded')
    else:
      self._reset_count()
      return resp

  def _inc_count(self):
    do_commit = self._safe_to_commit()
    # Not critical that this isn't atomic.
    self.user.gcal_api_error_count += 1
    if do_commit:
      db.session.commit()

  def _reset_count(self):
    do_commit = self._safe_to_commit()
    self.user.gcal_api_error_count = 0
    if do_commit:
      db.session.commit()

  # If there are pending changes, we don't do a commit here, on the
  # assumption that it will happen elsewhere.
  def _safe_to_commit(self):
    return len(db.session.new) + len(db.session.deleted) + len(db.session.dirty) == 0

  def get(self, *args, **kwargs):
    return self._with_error_handling('get', *args, **kwargs)

  def put(self, *args, **kwargs):
    return self._with_error_handling('put', *args, **kwargs)

  def patch(self, *args, **kwargs):
    return self._with_error_handling('patch', *args, **kwargs)

  def post(self, *args, **kwargs):
    return self._with_error_handling('post', *args, **kwargs)

  def delete(self, *args, **kwargs):
    return self._with_error_handling('delete', *args, **kwargs)


# The `get_oauth_session_for_user` method wraps up:
#
# (a) Retrieving the correct OAuth2 client (based on the token)
#
# (b) Refresh token handling. The token is refreshed as needed, and a
# token update on the model is queued in the db session.
#
# Note: It is the responsibility of the caller to ensure a
# `db.session.commit()` is performed at some point.
#

def get_oauth_session_for_user(user, expire_token=False):
  # `user`: A `User` instance.
  # `expire_token`: When `True`, simulates token expiration (for
  # test purposes).
  #
  def hook(newtoken):

    if 'refresh_token' not in newtoken:
      oldtoken = json.loads(user.tokens)
      newtoken['refresh_token'] = oldtoken['refresh_token']
    assert 'refresh_token' in newtoken

    user.tokens = json.dumps(newtoken)
    # Having this side-effect doesn't feel very natural to use. It
    # feels more like stashing the new token should be happening
    # outside of the transaction building that's being done by
    # calling code; needs thought.
    #
    # I wonder whether we ever really want to be in the middle of a db
    # transaction when making an api request. This could lead to poor
    # performance if stuff in the db gets locked for the duration of
    # the network request? If not, we could assume any caller has done
    # a `commit` before making requests with the oauth session, which
    # would enable us to commit the new token. (Should one be
    # acquired.)
    #
    # If we did this, we'd possibly like to check (at runtime) that
    # this assumption holds. One possibility might be to do a
    # `db.session.begin()` here, which will raise if a transaction has
    # already begun.
    db.session.add(user)
    # `db.commit` would be a bad idea. If the caller is mixing api
    # and db work this commit can cause a query to do an
    # auto-flush at an inconvenient time. e.g. When half way
    # through assembling an model, when the model is not yet fully
    # populated and can't be written to the db.
  token = json.loads(user.tokens)
  if expire_token:
    # This isn't superficial -- it triggers a token refresh api call.
    token['expires_at'] = time.time() - 1
  Config = GoogleAuth
  extra = {'client_id': Config.CLIENT_ID,
           'client_secret': Config.CLIENT_SECRET}
  google = OAuth2Session(Config.CLIENT_ID,
    token=token,
    auto_refresh_kwargs=extra,
    auto_refresh_url=Config.TOKEN_URI,
    token_updater=hook)

  return OAuthSession(google, user)

def chk_resp(resp):
  if resp is None:
    raise Exception('api error (response=None)')
  if not resp.ok:
    raise Exception(f'api error (status_code={resp.status_code},text={resp.text})')

# TODO: It's tempting to drop the `google` arg from
# `create_gcal_entry` and `update_gcal_entry`, and instead make an
# OAuthSession internally using `get_oauth_session_for_user` on
# `calendar` and `draft_event.calendar` respectively.

def list_gcal_entries(google, calendar, page_token=None, sync_token=None, single_events=True):
  assert type(single_events) == bool
  # There appears to be a bug in the gcal api, which leads to call to
  # list events to sometimes incorrectly return the empty list.
  #
  # Setting `maxResults` to something large is suggested as a
  # work-around, but I've occassionally seen the bug with this set to
  # 1000. Maybe set this higher?
  #
  # It's claimed that `singleEvents=True` also helps, which we use
  # throughout the app. I *have* seen a case where
  # `maxResults=1000,singleEvents=False` incorrectly returned the
  # empty list, but `maxResults=1000,singleEvents=True` worked.
  #
  # https://stackoverflow.com/a/55413860
  params = {'maxResults': 1000, 'singleEvents': single_events}
  if page_token is not None:
    params['pageToken'] = page_token
  if sync_token is not None:
    params['syncToken'] = sync_token
  resp = google.get(gcal_events_uri(calendar.gcal_id), params=params)
  if sync_token is not None and resp.status_code == 410:
    # Signal full sync required.
    # https://developers.google.com/calendar/api/guides/sync#full_sync_required_by_server
    return None
  chk_resp(resp)
  return resp.json()

def exists_gcal_entry(google, calendar, uid):
  params = {'iCalUID': f'{uid}@google.com', 'showHiddenInvitations': False}
  resp = google.get(gcal_events_uri(calendar.gcal_id), params=params)
  if resp and resp.ok:
    items = resp.json().get('items', [])
    return len(items) > 0
  else:
    return False

def get_gcal_entry(google, gcal_id, uid):
  uri = gcal_events_uri(gcal_id)
  resp = google.get(f'{uri}/{uid}')
  if resp is None:
    return
  chk_resp(resp)
  return resp.json()

# TODO: Generate the uid ourselves and write to db before calling
# gcal, else concurrent sync can trip us up [#124]
def create_gcal_entry(google, gcal_id, entry, params={}):
  """create a gcal entry for an event, in a given calendar"""
  # `google`: OAuthSession. (Must use the client/token from `calendar`)
  # `calendar`: A `Calendar` instance
  # `entry`: data for new gcal entry
  # returns: The uid of the new calendar entry.
  resp = google.post(gcal_events_uri(gcal_id), json=entry, params=params)
  if resp is None:
    return
  chk_resp(resp)
  return resp.json()['id']

def update_gcal_entry(google, gcal_id, entry, uid, params={}, patch=False):
  # The PUT update operation will re-create the event if it has been
  # removed from the calendar.
  uri = gcal_events_uri(gcal_id)
  method = google.patch if patch else google.put
  resp = method(f'{uri}/{uid}', json=entry, params=params)
  if resp is None:
    return
  chk_resp(resp)

# DANGER! Think carefully before calling this directly.
def delete_gcal_entry(google, gcal_id, uid):
    # Sanity check.
    if not uid.startswith(GCAL_EVENT_UID_PREFIX):
      raise Exception(f'Attempt to delete non-kron gcal entry uid={uid}')
    uri = gcal_events_uri(gcal_id)
    resp = google.delete(f"{uri}/{uid}")
    if resp is None:
      return
    # Event already deleted. This is distinct from 404 / not found.
    if resp.status_code == 410:
      return
    chk_resp(resp)

def watch_gcal_resource(google, resource, ttl):
  assert type(resource) in (User, Calendar)
  assert type(ttl) == int and ttl > 0
  if type(resource) == Calendar:
    uri = f'{gcal_events_uri(resource.gcal_id)}/watch'
  else:
    assert type(resource) == User
    uri = f'{GCAL_CALENDAR_LIST_URI}/watch'
  uuid = str(uuid4())
  hostname = app.config['GCAL_WEBHOOK_HOST']
  # By passing token here we have the option of switching away from
  # matching on the resource uri (in the webhook route) eventually.
  data = {'id': uuid,
          'type': 'web_hook',
          'token': type(resource).__name__.lower(),
          'address': f'https://{hostname}/gcal_webhook',
          'params': {'ttl': str(ttl)}} # seconds 'til expiration
  return google.post(uri, json=data)

def stop_gcal_channel(google, channel_id, resource_id):
  uri = 'https://www.googleapis.com/calendar/v3/channels/stop'
  data = {'id': channel_id, 'resourceId': resource_id}
  resp = google.post(uri, json=data)
  if resp is None:
    return
  if not resp.ok:
    print(f'stop_gcal_channel api error: status_code={resp.status_code}, text={resp.text}')
    return
  return resp # returns http 204 (no-content) on success

def get_gcal_calendar_metadata(google, calendar):
  resp = google.get(gcal_calendar_uri(calendar.gcal_id))
  if resp is None:
    return
  chk_resp(resp)
  return resp.json()

def list_gcal_calendars(google, show_deleted=False, show_hidden=False, max_results=100, page_token=None):
  params = dict(showDeleted=show_deleted, showHidden=show_hidden, maxResults=max_results)
  if page_token:
    params['pageToken'] = page_token
  resp = google.get(GCAL_CALENDAR_LIST_URI, params=params)
  if resp is None:
    return
  chk_resp(resp)
  return resp.json()

# Note: requires auth/calendar
def patch_gcal_calendar_list(google, calendar, entry):
  uri = gcal_calendar_list_uri(calendar.gcal_id)
  resp = google.patch(uri, json=entry)
  if resp is None:
    return
  chk_resp(resp)
  return resp.json()

def list_gcal_settings(google):
  resp = google.get(GCAL_SETTINGS_URI)
  if resp is None:
    return
  chk_resp(resp)
  return resp.json()

def get_gcal_setting(google, setting):
  return google.get(f'{GCAL_SETTINGS_URI}/{setting}')

def create_gcal_calendar(google, summary, description=None, timezone=None):
  data = dict(summary=summary)
  if description:
    data['description'] = desciption
  if timezone:
    data['timeZone'] = timezone
  resp = google.post(GCAL_CALENDARS_URI, json=data)
  chk_resp(resp)
  return resp.json()['id']

def gcal_can_revoke(token):
  assert type(token) is dict
  return any(key in token for key in ('refresh_token', 'access_token'))

# Once the access token has expired, it can't be revoked. We could
# refresh the access token and then revoke that. But instead, we
# first attempt to directly revoke the refresh token, which seems
# to work fine both before / after the access token has expired.
# If we don't have an refresh token, we'll try using the access
# token.
#
# https://developers.google.com/identity/protocols/oauth2/web-server#httprest_8
#
def gcal_revoke(token):
  assert type(token) is dict
  assert gcal_can_revoke(token)
  google = OAuth2Session(GoogleAuth.CLIENT_ID)
  t = token.get('refresh_token') or token['access_token']
  return google.post(f'https://oauth2.googleapis.com/revoke?token={t}')
