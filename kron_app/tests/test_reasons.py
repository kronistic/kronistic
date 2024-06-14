import pytest
from datetime import datetime, timedelta
from kron_app.reasons import impossible_because_users, unscheduled_because_events, unscheduled_because_users, unscheduled_because_window
from kron_app.tests.helpers import days, hrs, isinit, isscheduled, isunscheduled, mins, mkevent_for_solver_tests as mkevent, mkfixedevent, mkuser, schedule, mkavail
from kron_app.run_solver import run_solver

# This implicitly does test db setup/teardown for all tests in this
# module. The alternative is to add the `testdb` fixture to individual
# tests as required.
@pytest.fixture(scope='function', autouse=True)
def autotestdb(testdb):
  pass

@pytest.fixture(scope='function')
def basetime():
  now = datetime.utcnow()
  #rounded to hour, two hours from now in order to not intersect freeze window:
  basetime = now.replace(second=0, microsecond=0, minute=0)+timedelta(hours=2)
  return basetime

def test_unsat_oneuser(utcnow,basetime):
  u = mkuser()
  e = mkevent(u, length=mins(30), wstart=basetime, wlength=hrs(4), attendees=[u.id])
  mkavail(u, basetime+hrs(6), hrs(12))
  assert isinit(e)

  #check impossible
  ispossible, unavailable_sets, unavailable_users = impossible_because_users(e)
  assert not ispossible
  assert unavailable_sets == [(str(u.id),)]
  assert unavailable_users == [(str(u.id),True)]

  #check unscheduled because attendees, 
  # won't be solvable because sole attendee is unavailable (events with no attendees are unscheduled)
  leftovers, draft_start = unscheduled_because_users(e)
  assert draft_start is None
  # assert leftovers == {str(u.id)}

  #check uscheduled because other meetings (false)

  #check unscheduled because window 
  new_end = unscheduled_because_window(e)
  assert new_end is not None
  assert new_end > e.window_end


def test_unsat_twouser(utcnow,basetime):
  u = mkuser()
  u2 = mkuser("foo")
  e = mkevent(u, length=mins(30), wstart=basetime, wlength=hrs(4), attendees=[u.id,u2.id])
  e2 = mkevent(u, length=hrs(4), wstart=basetime, wlength=hrs(4), attendees=[u.id])
  schedule(e2,basetime,[u.id])
  mkavail(u, basetime, hrs(12))
  mkavail(u2,start_at=basetime,length=hrs(12))

  #check impossible
  ispossible, unavailable_sets, unavailable_users = impossible_because_users(e)
  assert ispossible
  assert unavailable_sets == []
  assert unavailable_users == []

  #check unscheduled because attendees
  leftovers, draft_start = unscheduled_because_users(e)
  assert draft_start is not None
  assert leftovers == {str(u.id)}

  #check uscheduled because other meetings (false)
  bumped, draft_start = unscheduled_because_events(e)
  assert draft_start is not None
  assert bumped == [str(e2.id)]

  #check unscheduled because window 
  new_end = unscheduled_because_window(e)
  assert new_end is not None
  assert new_end > e.window_end



def test_extend_window(utcnow,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id])
  e2 = mkevent(u3, length=hrs(3), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])
  f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 
  initial_window_end = e2.window_end
  mkavail(u1, start_at=utcnow, length=hrs(12))
  mkavail(u2, start_at=utcnow, length=hrs(12))
  mkavail(u3, start_at=utcnow, length=hrs(12))
  tosync, emails = run_solver()
  assert isscheduled(e1) or isscheduled(e2)
  assert isunscheduled(e1) or isunscheduled(e2)
  e= e1 if isunscheduled(e1) else e2
  new_end = unscheduled_because_window(e)
  assert new_end is not None
  assert new_end > e.window_end

def test_extend_2windows(utcnow,basetime):
    u1 = mkuser('n')
    u2 = mkuser('p')
    u3 = mkuser('e')
    e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id])
    e2 = mkevent(u3, length=hrs(3), wstart=basetime, wlength=hrs(3), attendees=[u1.id, u3.id])
    f1 = mkfixedevent(u2,start_at=basetime,length=hrs(3)) 
    f2 = mkfixedevent(u3,start_at=basetime,length=hrs(1)) 
    initial_window_end1 = e1.window_end
    initial_window_end2 = e2.window_end
    mkavail(u1, start_at=utcnow, length=hrs(12))
    mkavail(u2, start_at=utcnow, length=hrs(12))
    mkavail(u3, start_at=utcnow, length=hrs(12))
    tosync, emails = run_solver()
    assert isunscheduled(e1)
    assert isunscheduled(e2)
    new_end = unscheduled_because_window(e1)
    assert new_end is not None
    assert new_end > e1.window_end
    e1.window_end=new_end #FIXME: need to db commit?
    new_end = unscheduled_because_window(e2)
    assert new_end is not None
    assert new_end > e2.window_end

