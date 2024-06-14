from datetime import time
from kron_app import app
from kron_app.gcal_api import GCAL_EVENT_UID_PREFIX

# @app.template_global()
# def foo():
#   return 'bar'

@app.template_global()
def fmtuid(uid):
  if uid and uid.startswith(GCAL_EVENT_UID_PREFIX):
    return '<KRON>' + uid[len(GCAL_EVENT_UID_PREFIX):]
  else:
    return uid

@app.template_filter('tosentence')
def tosentence(items):
  if type(items) != list: # e.g. generator
    items = list(items)
  if len(items) == 0:
    return ''
  last = items[-1]
  rest = items[:-1]
  return ', '.join(rest) + (' and ' if rest else '') + last

@app.template_filter('pluralize')
def pluralize(noun, items_or_count, show_count=False):
  """
  'meeting' | pluralize(1) => 'meeting'
  'meeting' | pluralize(2) => 'meetings'
  'meeting' | pluralize([m1,m2]) => 'meetings'
  'attendee' | pluralize(1, show_count=True) => '1 attendee'
  'attendee' | pluralize(2, show_count=True) => '2 attendees'
  """
  count = items_or_count if type(items_or_count) == int else len(items_or_count)
  pre = f'{str(count)} ' if show_count else ''
  suf = '' if count == 1 else 's'
  return pre + noun + suf

@app.template_global()
def fmt_available_time(days, start_time, end_time):
  assert type(days) == list and len(days) > 0
  days = sorted(set(days))
  assert len(days) <= 7
  start = time(start_time).strftime('%-H:%M')
  end = time(end_time).strftime('%-H:%M')
  DAYNAMES = 'Mondays Tuesdays Wednesdays Thursdays Fridays Saturdays Sundays'.split()
  if days == [0,1,2,3,4]:
    daystr = 'weekdays'
  elif len(days) == 6:
    missing = 21-sum(days)
    daystr = f'any day except {DAYNAMES[missing]}'
  elif len(days) == 7:
    daystr = 'any day'
  else:
    daystr = f'{tosentence(list(DAYNAMES[d] for d in days))}'
  return f'{start} - {end} on {daystr}'

EXT_HOST = 'https://kronistic.com'
EXT_URLS = {
  'home': EXT_HOST,
  'help': f'{EXT_HOST}/faq/',
  'privacy': f'{EXT_HOST}/privacy/',
  'terms': f'{EXT_HOST}/terms/',
  'blog': f'{EXT_HOST}/blog/',
  'product': f'{EXT_HOST}/product-and-pricing/',
  'about': f'{EXT_HOST}/about-kronistic/',
  'feedback': f'{EXT_HOST}/feedback/',
}

@app.template_global()
def ext_url_for(name, _anchor=None):
  url = EXT_URLS[name]
  if _anchor:
    url += f'#{_anchor}'
  return url

@app.template_global()
def url_for_static(filename):
  v = 1 # Static asset version for cache busting.
  return f'/static/{filename}?v={v}'
