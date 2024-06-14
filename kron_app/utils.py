from uuid import uuid4
import base64
from dateutil.tz import UTC
from datetime import datetime, timedelta
from urllib.parse import urlparse
from kron_app import app
from kron_app.tznames import TZNAMES

def getstr(d, k):
    # Get a value from a dict. Return empty string when key is either
    # missing or value is None.
    return d.get(k) or ''

def ids(xs):
    return [x.id for x in xs]

def flatten(xss):
  return [x for xs in xss for x in xs]

def uid():
  return str(uuid4()).replace('-', '')

def uid32():
    return base64.b32encode(uuid4().bytes).decode('ascii')[:26].lower()

class DotDict(dict):
    """
    a dictionary that supports dot notation 
    as well as dictionary access notation 
    usage: d = DotDict() or d = DotDict({'val1':'first'})
    set attributes: d.val2 = 'second' or d['val2'] = 'second'
    get attributes: d.val2 or d['val2']
    """
    # __getattr__ = dict.__getitem__
    #switch error types so deepcopy will work..
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __init__(self, dct):
        for key, value in dct.items():
            if hasattr(value, 'keys'):
                value = DotDict(value)
            self[key] = value

def dotdict(**kwargs):
  return DotDict(kwargs)

def dictunion(d1, d2):
  return {**d1, **d2}

__TZOPTIONS = [(t,t.replace('_',' ')) for t in TZNAMES]

def tznames():
    return TZNAMES

def tzoptions():
    return __TZOPTIONS

def to_utc(dt, tz):
    assert dt.tzinfo is None, 'expected a naive datetime'
    assert tz is not None
    return dt.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)

def from_utc(dt, tz):
    assert dt.tzinfo is None, 'expected a naive datetime'
    assert tz is not None
    return dt.replace(tzinfo=UTC).astimezone(tz).replace(tzinfo=None)

@app.template_global()
def from_utc_to_s(dt, tz, short=False, utcnow=None):
    assert dt.tzinfo is None, 'expected a naive datetime'
    assert tz is not None
    if utcnow is None:
        utcnow = datetime.utcnow()
    if short:
        fmt = '%Y-%m-%d %H:%M %Z'
    elif (dt - utcnow) > timedelta(days=300): # ~10 months
        fmt = '%a, %B %-d, %Y, at %-H:%M %Z'
    else:
        fmt = '%a, %B %-d, at %-H:%M %Z'
    return dt.replace(tzinfo=UTC).astimezone(tz).strftime(fmt)

def advance_to_midnight(dt):
    assert dt.tzinfo is None, 'expected a naive datetime'
    return (dt + timedelta(days=1) - timedelta(microseconds=1)).replace(hour=0, minute=0, second=0, microsecond=0)

def sanitize_url(url, scheme, host):
    # Ensure we don't silently fail to sanitize if passed empty string(s).
    if not scheme or not host:
        raise ValueError('scheme and host must be given')
    return urlparse(url)._replace(scheme=scheme, netloc=host).geturl()
