from copy import deepcopy
from sqlalchemy import cast, update, String
from sqlalchemy.dialects.postgresql import array, ARRAY, JSONB
from kron_app import db
from kron_app.utils import flatten
from kron_app.users import find_user_by_primary_email
from kron_app.models import User, FixedEvent
from kron_app.changes import record_current
from kron_app.utils import ids

# Properties of groups
# --------------------

# Groups are dicts mapping a group name to a list of its members.
#
# A member is either the name of another group or the primary email
# address of a kron user.
#
# Users are distinguished from groups by checking for the presence of
# '@', which can't appear in group names.
#
# References to non-existent groups or users are not allowed. (This is
# implemented by `group_members_valid` which needs to be called before
# create/updating a group.)
#
# Loops are allowed.


# TODO:

# read-modify-write for groups isn't concurrent safe. fix or note.

# how should users be represented? wouldn't user id be better than
# (primary) email?

# prefixing with `group` is a bit pointless -- import module and use
# e.g. `groups.update` instead?


# This is more appropriate than the helper in `mask_utils` in that it
# doesn't return left over group names e.g. when expanding e.g.
# mutually.
#
# This assumes that a group doesn't reference non-existent groups.
# (This is an invariant which the UI is intended to preserve, so this
# should be OK.)
def unpack_groups(nick, groups, seen=[]):
  if nick in seen:
    return set()
  ms = next((v for k,v in groups.items() if k.lower()==nick.lower()), [])
  ns = [n.lower() for n in groups.keys()]
  return set(flatten(unpack_groups(m, groups, seen+[nick]) if m.lower() in ns else [m] for m in ms))

def get_deps(nick, groups, seen=[]):
  if nick in seen:
    return set()
  direct_deps = set(n for n,m in groups.items() if nick in m)
  return {nick} | direct_deps | set(flatten(get_deps(n, groups, seen+[nick]) for n in direct_deps))

def get_name_and_type(nick_or_email, groups):
  # assumes groups are well-formed
  if '@' in nick_or_email:
    u = find_user_by_primary_email(nick_or_email)
    assert u, 'invalid email in groups'
    return u.name, 'user'
  else:
    assert nick_or_email in groups, 'invalid nick in groups'
    return nick_or_email, 'group'

def group_members_valid(groups, members):
  def isvalid(nick_or_email):
    if '@' in nick_or_email:
      return find_user_by_primary_email(nick_or_email) is not None
    else:
      return nick_or_email in groups
  return all(isvalid(nick_or_email) for nick_or_email in members)

def group_add(groups, nick, members):
  out = deepcopy(groups) # non-destructive to match other similar methods
  out[nick] = members
  return out

def group_update(groups, nick, newnick, members):
  def rename(ms):
    return [newnick if m==nick else m for m in ms]
  out = {}
  for n,ms in groups.items():
    if n!=nick:
      out[n] = rename(ms)
  out[newnick] = rename(members)
  return out

def group_delete(groups, nick):
  out = {}
  for n,ms in groups.items():
    if n!=nick:
      out[n] = [m for m in ms if m != nick]
  return out
