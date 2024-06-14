import pytest
from datetime import datetime, timedelta
from sqlalchemy import desc
from kron_app import db
from kron_app.tests.helpers import mins, hrs, days, mkuser, mkevent_for_solver_tests as mkevent, isunscheduled, isscheduled, schedule, mkclean, mkdirty, mkfinal, mkfixedevent, mkspace, setpriority, mkavail
from kron_app.models import SolverLog
from kron_app.run_solver import SolverError, run_solver
from kron_app.utils import ids

# This implicitly does test db setup/teardown for all tests in this
# module. The alternative is to add the `testdb` fixture to individual
# tests as required.
@pytest.fixture(scope='function', autouse=True)
def autotestdb(testdb):
    pass

@pytest.fixture(scope='function')
def now():
    return datetime(2022,4,13,hour=10,minute=12)

@pytest.fixture(scope='function')
def basetime():
  now = datetime(2022,4,13,hour=10,minute=12)
  #rounded to hour, two hours from now in order to not intersect freeze window:
  basetime = now.replace(second=0, microsecond=0, minute=0)+timedelta(hours=2)    
  return basetime


# #make a time util:
# now = d(2022,4,13,hour=10,minute=12)
# basetime = now.replace(second=0, microsecond=0, minute=0)
# def mt(i):
# 	return basetime+td(hours=i+1)


def test_one_mtg(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  #make sure the meeting is soonest:
  assert e1.draft_start == basetime
  assert len(emails) == 0
  assert tosync == [e1.id]

def test_two_mtg(now,basetime):
  """two events to make sure they don't overlap"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  mkavail(u1, start_at=basetime, length=hrs(12))
  mkavail(u2, start_at=basetime, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])
  e2 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  assert isscheduled(e1)
  assert isscheduled(e2)
  assert e1.draft_start==basetime or e2.draft_start==basetime
  assert e1.draft_start==basetime+hrs(2) or e2.draft_start==basetime+hrs(2)

def test_two_mtg_oneslot(now,basetime):
  """two events with no overlapping attendees to make sure they do overlap"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  mkavail(u1, start_at=basetime, length=hrs(12))
  mkavail(u2, start_at=basetime, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id])
  e2 = mkevent(u2, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u2.id])

  tosync, emails = run_solver(now)
  assert isscheduled(e1)
  assert isscheduled(e2)
  assert e1.draft_start==basetime and e2.draft_start==basetime
  # assert e1.draft_start==basetime+hrs(2) or e2.draft_start==basetime+hrs(2)


# @pytest.mark.xfail(reason='https://github.com/kronistic/kron-app/pull/216#issue-1230286621')
# def test_two_mtg_nogaps():
#   floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(10), id="m1", length=td(hours=2)),
#   FloatMeeting(attendees=["noah"], window_start=mt(0),window_end=mt(10), id="m2", length=td(hours=2)),]
#   fixies = [FixedMeeting(attendees=["noah"],start=mt(2), length=td(hours=2), id="b1")]
#   result, schedule, unschedueled_ids = solver(floaties,fixies,now,config={'nogaps':True})
#   print(schedule)
#   assert(result)
#   assert(schedule[0].end==schedule[1].start or schedule[1].end==schedule[0].start)

def test_hard_simple_sat(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id])
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert isscheduled(e2)
  #make sure the meeting is soonest:
  assert e1.draft_start == basetime
  assert len(emails) == 0
  assert set(tosync) == {e1.id,e2.id}

def test_panic_repair(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=basetime+hrs(2), length=hrs(4))
  mkavail(u2, start_at=basetime, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime+hrs(2), wlength=hrs(2), attendees=[u1.id, u2.id])
  e3 = mkevent(u1, length=hrs(2), wstart=basetime+hrs(2), wlength=hrs(2), attendees=[u1.id, u2.id])
  schedule(e1,basetime,[u1.id,u2.id])
  mkclean(e1)
  schedule(e3,basetime,[u1.id,u2.id])
  mkclean(e3)
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(24), attendees=[u1.id, u3.id])
  mkdirty(e2)

  assert isscheduled(e1)
  assert isscheduled(e3)
  tosync, emails = run_solver(now)

  assert (isscheduled(e1) and isunscheduled(e3)) ^ (isscheduled(e3) and isunscheduled(e1))
  assert isscheduled(e2)
  assert len(emails) == 1
  assert set(tosync) == {e1.id,e2.id,e3.id}

def test_regression_issue_518(now,basetime):
    u1 = mkuser('n')
    # e1 leads to panic because scheduled outside of available hours.
    e1 = mkevent(u1, length=hrs(1), wstart=basetime+hrs(2), wlength=hrs(2), attendees=[u1.id])
    schedule(e1,basetime+hrs(2),[u1.id])
    mkclean(e1)
    # trigger inclusion of e1 in problem without it been in candidate set.
    mkspace(u1, e1.window_start, e1.window_end)
    tosync, emails = run_solver(now)
    assert isunscheduled(e1)
    assert len(emails) == 1

def test_timeout_sat(now,basetime):
  #make a problem that takes lonng enough to set the timout low enough to hit timeout_timeout in repair.. 
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  for u in [u1,u2,u3]:
    mkavail(u, start_at=basetime, length=hrs(2))
    mkavail(u, start_at=basetime+hrs(4), length=hrs(2))
    mkavail(u, start_at=basetime+hrs(8), length=hrs(2))
    mkavail(u, start_at=basetime+hrs(10), length=hrs(2))

  es = [mkevent(u3, length=mins(30), wstart=basetime, wlength=hrs(20), attendees=[u1.id, u2.id, u3.id]) for i in range(10)]

  try:
    tosync, emails = run_solver(now=now,config={'timeout': 1})
  except Exception as e:
    #this is what should happen
    assert isinstance(e,SolverError)
    return
  
  assert False #should not get here

def test_sat_pass2(now,basetime):
  #make a problem that takes lonng enough to set the timout low enough to hit sat_2-lra_sat_2.. 
  #NOTE: this test may fail on a faster or slower computer, since it depends on time to optimum being longer than timeout, but time to solve hard constraints not.
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  for u in [u1,u2,u3]:
    mkavail(u, start_at=basetime, length=hrs(2))
    mkavail(u, start_at=basetime+hrs(4), length=hrs(2))
    mkavail(u, start_at=basetime+hrs(8), length=hrs(2))
    mkavail(u, start_at=basetime+hrs(10), length=hrs(2))

  es = [mkevent(u3, length=mins(30), wstart=basetime, wlength=hrs(20), attendees=[u1.id, u2.id, u3.id]) for i in range(10)]

  tosync, emails = run_solver(now=now,config={'timeout': 100})
  entries = SolverLog.query.order_by(desc('created_at')).limit(20).all()
  entries = [e.data for e in entries]
  assert entries[0]['result_code']=='sat_2-lra_sat_1'
  assert all([isscheduled(e) for e in es])

# def test_lra_order(now,basetime):
#   #make a problem that takes lonng enough to set the timout low enough to hit sat_2-lra_sat_2.. 
#   #NOTE: this test may fail on a faster or slower computer, since it depends on time to optimum being longer than timeout, but time to solve hard constraints not.
#   u1 = mkuser('n')
#   u2 = mkuser('p')
#   u3 = mkuser('e')
#   for u in [u1,u2,u3]:
#     mkfixedevent(u, start_at=basetime, length=hrs(10), kron_directive='@kron')

#   es = [mkevent(u3, length=mins(30), wstart=basetime, wlength=hrs(20), attendees=[u1.id, u2.id, u3.id]) for i in range(5)]

#   for i,e in enumerate(es):
#     schedule(e,basetime+i*mins(30),[u1.id, u2.id, u3.id]) 
#   tosync, emails = run_solver(now=now)

#   entries = SolverLog.query.order_by(desc('created_at')).limit(20).all()
#   entries = [e.data for e in entries]
#   assert entries[0]['result_code']=='sat_2-lra_sat_2'
#   assert all([isscheduled(e) for e in es])


def test_hard_simple_unsat(now,basetime):
  """unsat because there isn't enough time for both meetings"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id])
  e2 = mkevent(u3, length=hrs(3), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 

  tosync, emails = run_solver(now)

  assert (isscheduled(e1) and isunscheduled(e2)) or (isscheduled(e2) and isunscheduled(e1))
  assert len(emails) == 1
  assert set(tosync) == {e1.id,e2.id}

def test_freeze_horizon_sat(now,basetime):
  """ now=(hour=10,minute=12)
      now+freeze=(hour=13,minute=12) 
      window_end=(hour=16,minute=0)"""

  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id], freeze_horizon=hrs(3))
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert isscheduled(e2)
  #because e1 has freeze horizon conflicting with first 2hr slot, e2 should be first:
  assert e2.draft_start == basetime
  assert len(emails) == 0
  assert set(tosync) == {e1.id,e2.id}

def test_freeze_horizon_sat2(now,basetime):
  """i can't remember why this test was needed..."""
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id], freeze_horizon=mins(48+110))
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert isscheduled(e2)
  #because e1 has freeze horizon conflicting with first 2hr slot, e2 should be first:
  assert e2.draft_start == basetime
  assert len(emails) == 0
  assert set(tosync) == {e1.id,e2.id}

def test_freeze_horizon_unsat(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id], freeze_horizon=hrs(3))
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id], freeze_horizon=hrs(3))

  tosync, emails = run_solver(now)
  #one of the two meeting will be unsat since freeze horizons shorten windows to 3 hrs..
  assert isscheduled(e1) or isscheduled(e2)
  assert isunscheduled(e1) or isunscheduled(e2)
  assert len(emails) == 1
  assert set(tosync) == {e1.id,e2.id}

def test_rescheduled_final_notification(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  e1 = mkevent(u1, length=hrs(1), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id], freeze_horizon=hrs(1))
  schedule(e1, basetime, [u1.id, u2.id])
  assert isscheduled(e1)
  mkfinal(e1)
  tosync, emails = run_solver(now)
  assert len(emails) == 0
  f1 = mkfixedevent(u1,basetime,hrs(1))
  mkdirty(f1)
  tosync, emails = run_solver(now)
  assert isscheduled(e1)
  assert e1.draft_start==basetime+hrs(1)
  assert len(emails) == 2
  assert set((e[0][0] for e in emails)) == set((u1.email, u2.email))

def test_freeze_horizon_final(now,basetime):
  """test that a final meeting ignores free horizon and schedules as soon as possible after draft time"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id], freeze_horizon=hrs(3))
  _,_ = run_solver(basetime-hrs(3)) #freeze horizo is basetime
  assert isscheduled(e1)
  assert e1.draft_start==basetime
  mkfinal(e1)
  f1 = mkfixedevent(u1,basetime,hrs(1))
  mkdirty(f1)
  tosync, emails = run_solver(now)

  assert isscheduled(e1)
  assert e1.draft_start==basetime+hrs(1) #as soon as possible after draft start...

def test_optional_past(now,basetime):
  """this test correct handling when there's an optional meeting that is in the past (and therefore has an empty mask)"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=now-hrs(12), wlength=hrs(4), attendees=[u1.id, u2.id], freeze_horizon=hrs(3))
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id], freeze_horizon=hrs(1))

  tosync, emails = run_solver(now)

  assert not isscheduled(e1)
  assert isscheduled(e2)
  # print(f"  basetime {basetime}, e1: {e1.draft_start} -- {e1.draft_end}, e2: {e2.draft_start} -- {e2.draft_end}")
 
  # assert e1.window_end==basetime+hrs(12) or e2.window_end==basetime+hrs(12)
  assert len(emails) == 1
  assert set(tosync) == {e1.id,e2.id}

def test_freeze_horizon_offhour_sat(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=mins(30), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u2.id], freeze_horizon=mins(15))

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert len(emails) == 0
  assert tosync == [e1.id]

def test_optional_attendees(now,basetime):
  """sat by making one optional attendee not attend"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u2, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u2.id], optionalattendees=[u1.id])
  e2 = mkevent(u3, length=hrs(3), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert isscheduled(e2)
  #u1 should have been left out of e1, since thethe only way to fit both meetings is to schedule at same time..
  assert e1.draft_attendees == [u2.id]
  assert len(emails) == 0
  assert set(tosync) == {e1.id,e2.id}

def test_optional_attendees2(now,basetime):
  """one optional attendee can attend"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u2, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u2.id], optionalattendees=[u1.id])
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert isscheduled(e2)
  #u1 should be included in e1.
  assert set(e1.draft_attendees) == {u1.id,u2.id}
  assert len(emails) == 0
  assert set(tosync) == {e1.id,e2.id}

def test_optional_attendee_availability(now,basetime):
  """test respect for optional attendee kronduty availability"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  mkavail(u1, start_at=basetime+hrs(1), length=hrs(12))
  mkavail(u2, start_at=basetime+hrs(0), length=hrs(12))

  e1 = mkevent(u2, length=hrs(1), wstart=basetime, wlength=hrs(4), attendees=[u2.id], optionalattendees=[u1.id])
  # f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert e1.draft_attendees == [u2.id,u1.id]
  assert e1.draft_start == basetime+hrs(1)

def test_one_optional_attendee_unavailable(now,basetime):
  """test that a meeting the sole optional attendee can't make it doesn't get scheduled"""
  u = mkuser()
  e = mkevent(u, length=mins(30), wstart=basetime, wlength=hrs(4), attendees=[], optionalattendees=[u.id])
  mkavail(u, basetime+hrs(6), hrs(12))

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isunscheduled(e)

def test_optional_attendees_unavailable(now,basetime):
  """test that a meeting where no attendees can make it doesn't get scheduled"""
  u1 = mkuser('n')
  u2 = mkuser('p')
  mkavail(u1, start_at=basetime, length=hrs(2))
  mkavail(u2, start_at=basetime, length=hrs(2))

  e1 = mkevent(u2, length=hrs(2), wstart=basetime+hrs(1), wlength=hrs(4), attendees=[], optionalattendees=[u1.id,u2.id])
  # f1 = mkfixedevent(u2,start_at=basetime+hrs(2),length=hrs(4)) 

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert e1.draft_attendees == []
  assert isunscheduled(e1)

def test_optional_attendees_priority(now,basetime):
  """two optional attendees but only one or the other can make it, 
  should choose one with higher priority """
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=basetime, length=hrs(3))
  mkavail(u2, start_at=basetime, length=hrs(3))
  mkavail(u3, start_at=basetime, length=hrs(2))

  e1 = mkevent(u1, length=hrs(1), wstart=basetime+hrs(1), wlength=hrs(4), attendees=[u1.id], optionalattendees=[u2.id,u3.id])
  #e2 is here so that priorities are not normed to 50
  e2 = mkevent(u2, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u2.id,u3.id], optionalattendees=[])

  setpriority(e1,u2,0)
  setpriority(e1,u3,100)

  #fixed event to make u2 unavailable at the same time as u3
  f1 = mkfixedevent(u2,start_at=basetime+hrs(1),length=hrs(1)) 

  tosync, emails = run_solver(now)
  db.session.rollback()

  print(f"draft start {e1.draft_start}, basetime {basetime}")
  assert isscheduled(e1)
  #u2 should have been left out of e1 because u3 assigned higher priority
  assert set(e1.draft_attendees) == {u1.id,u3.id}

  #now change priorities so that u2 is preferred
  setpriority(e1,u2,100)
  setpriority(e1,u3,0)
  mkdirty(e1)

  tosync, emails = run_solver(now)

  assert isscheduled(e1)
  #u3 should have been left out of e1 because u2 assigned higher priority
  assert set(e1.draft_attendees) == {u1.id,u2.id}

# one kronduty big enough for event
def test_kronduty_just_fit(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=basetime, length=hrs(2))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  #make sure the meeting is soonest:
  assert e1.draft_start == basetime
  assert len(emails) == 0
  assert tosync == [e1.id]

# one kronduty too small for event, another that fits it
def test_kronduty_avoid_too_small(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=basetime, length=hrs(1))
  mkavail(u1, start_at=basetime+hrs(4), length=hrs(2))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  #make sure the meeting in second kronduty slot:
  assert e1.draft_start == basetime+hrs(4)
  assert len(emails) == 0
  assert tosync == [e1.id]

# two adjacent kronduties each too small for event but together big enough
def test_kronduty_two_together(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=basetime, length=hrs(1))
  mkavail(u1, start_at=basetime+hrs(1), length=hrs(1))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  #make sure the meeting in second kronduty slot:
  assert e1.draft_start == basetime
  assert len(emails) == 0
  assert tosync == [e1.id]

# two kronduties each too small for event with small gap between
def test_kronduty_two_with_gap(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=basetime, length=hrs(1))
  mkavail(u1, start_at=basetime+mins(75), length=hrs(1))
  mkavail(u1, start_at=basetime+hrs(4), length=hrs(2))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(10), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  #make sure the meeting in second kronduty slot:
  assert e1.draft_start == basetime+hrs(4)
  assert len(emails) == 0
  assert tosync == [e1.id]

def test_ifneeded(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u2, start_at=basetime, length=hrs(1), cost=1)
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u2, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id])
  e2 = mkevent(u3, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u3.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  assert isscheduled(e2)
  print(f"  basetime {basetime}, e1: {e1.draft_start} -- {e1.draft_end}, e2: {e2.draft_start} -- {e2.draft_end}")
  #make sure the meeting without ifneeded conflict is soonest:
  assert e2.draft_start == basetime
  assert len(emails) == 0
  assert set(tosync) == {e1.id,e2.id}

#ifneeded slope test: event should prefer to overlap ifneeded time as little as possible. this won't happen with the stepwise ifneeded objective currently used (to ennable wmaxsmt formulation of ifneeded objective)
@pytest.mark.xfail(reason='https://github.com/kronistic/kron-app/pull/336/commits/e3eddbf2455a51dbb895488f2f6453b7752f9245')
def test_ifneeded_overlap(now,basetime):
  u1 = mkuser('n')
  u2 = mkuser('p')
  u3 = mkuser('e')
  mkavail(u1, start_at=now, length=hrs(12))
  mkavail(u2, start_at=now, length=hrs(12))
  mkavail(u2, start_at=basetime, length=hrs(2), cost=1)
  mkavail(u3, start_at=now, length=hrs(12))

  e1 = mkevent(u2, length=hrs(2), wstart=basetime, wlength=hrs(3), attendees=[u1.id, u2.id])

  tosync, emails = run_solver(now)
  db.session.rollback()

  assert isscheduled(e1)
  print(f"  basetime {basetime}, e1: {e1.draft_start} -- {e1.draft_end}")
  #make sure the meeting without ifneeded conflict is soonest:
  assert e1.draft_start == basetime+hrs(1)
  assert len(emails) == 0
  assert tosync == [e1.id]

def test_nan_bug_issue_574_repro(now,basetime):
    # this test got watered down when we removed differential
    # availability (#739). a fixed event with infinite cost is now
    # made by giving an invalid @kron directive. like the original
    # test for #574, this will fail (and for the same reason) if
    # `kronduty_masks` doesn't skip over fixies with infinte cost.
    u1 = mkuser()
    mkavail(u1, start_at=basetime, length=hrs(3))
    k1 = mkfixedevent(u1, start_at=basetime+hrs(2), length=hrs(1), kron_directive='@kron foo bar')
    e1 = mkevent(u1, length=mins(30), wstart=basetime, wlength=hrs(3), attendees=[u1.id])
    tosync, emails = run_solver(now)

#TODO: test that two adjacent ifneeded times act the same as one longer one

#TODO: add tests for all day fixed events (cf. old_test_get_fixed_events.py)
#TODO: add tests for optional meetings
#TODO: add tests where make_event_mask arg fixed_draft isn't empty. currently build_problem adds all possible draft events...


