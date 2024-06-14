import pytest
from datetime import datetime as d
from datetime import timedelta as td
from kron_app.solver.utils import FloatMeeting, FixedMeeting
from kron_app.solver.solver import solver

#a bunch of unit tests for the solver


#make a time util:
now = d(2022,4,13,hour=10,minute=12)
basetime = now.replace(second=0, microsecond=0, minute=0)
def mt(i):
	return basetime+td(hours=i+1)


def test_one_mtg():
  ws=mt(0)
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=ws,window_end=mt(10), id="m1", length=td(hours=2))]
  fixies = []
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  print(schedule)
  assert(result)
  #make sure the meeting is soonest:
  assert(schedule[0].start==ws)

@pytest.mark.xfail(reason='https://github.com/kronistic/kron-app/pull/216#issue-1230286621')
def test_two_mtg_nogaps():
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(10), id="m1", length=td(hours=2)),
  FloatMeeting(attendees=["noah"], window_start=mt(0),window_end=mt(10), id="m2", length=td(hours=2)),]
  fixies = [FixedMeeting(attendees=["noah"],start=mt(2), length=td(hours=2), id="b1")]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime,config={'nogaps':True})
  print(schedule)
  assert(result)
  assert(schedule[0].end==schedule[1].start or schedule[1].end==schedule[0].start)

def test_hard_simple_sat():
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=2))
        ]
  fixies = [
        FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1"),
        ]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  print(schedule)
  assert(result)
  assert((schedule[0].start==mt(0) and "paul" in schedule[0].actualattendees) or
    (schedule[1].start==mt(0) and "paul" in schedule[1].actualattendees))
  # assert(schedule==[DraftMeeting(id='m1', attendees=['noah', 'paul'], optionalattendees=[], window_start=datetime.datetime(2022, 4, 13, 11, 0), window_end=datetime.datetime(2022, 4, 13, 15, 0), freeze_horizon=datetime.timedelta(0), length=datetime.timedelta(seconds=7200), priority=0, is_optional=False, is_fixed=False, start=datetime.datetime(2022, 4, 13, 11, 0), end=datetime.datetime(2022, 4, 13, 13, 0), actualattendees=['noah', 'paul']), DraftMeeting(id='m2', attendees=['noah', 'emily'], optionalattendees=[], window_start=datetime.datetime(2022, 4, 13, 11, 0), window_end=datetime.datetime(2022, 4, 13, 15, 0), freeze_horizon=datetime.timedelta(0), length=datetime.timedelta(seconds=7200), priority=0, is_optional=False, is_fixed=False, start=datetime.datetime(2022, 4, 13, 13, 0), end=datetime.datetime(2022, 4, 13, 15, 0), actualattendees=['noah', 'emily'])])

def test_hard_simple_unsat():
  """unsat because there isn't enough time for both meetings"""
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=3))
        ]
  fixies = [
        FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1"),
        ]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  assert(not result)

def test_freeze_horizon_sat():
  """ now=(hour=10,minute=12)
      now+freeze=(hour=12,minute=12) 
      window_end=(hour=15,minute=0)"""
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2), freeze_horizon=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=2))
        ]
  fixies = []
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  print(schedule)
  assert(result)

def test_freeze_horizon_sat2():
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2), freeze_horizon=td(minutes=48+50)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(2), id="m2", length=td(hours=2))
        ]
  fixies = []
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  print(schedule)
  assert(result)

def test_freeze_horizon_unsat():
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2), freeze_horizon=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=2),  freeze_horizon=td(hours=2))
        ]
  fixies = []
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  assert(not result)

def test_freeze_horizon_offhour_sat():
  floaties=[FloatMeeting(attendees=["noah","paul"], 
    window_start=basetime,
    window_end=basetime+td(hours=1), 
    id="m1", length=td(minutes=30), 
    freeze_horizon=td(minutes=15))]
  fixies = []
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  print(schedule)
  assert(result)

def test_optional_attendees():
  """sat by making one optional attendee not attend"""
  floaties=[FloatMeeting(attendees=["paul"], optionalattendees=["noah"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=3))
        ]
  fixies = [
        FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1"),
        ]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  assert(result)
  print(schedule)
  assert(schedule[0].actualattendees==["paul"])
  # assert(schedule['actualattendees'][0]==["paul"])

def test_optional_attendees2():
  """one optional attendee can attend"""
  floaties=[FloatMeeting(attendees=["paul"], optionalattendees=["noah"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=2))
        ]
  fixies = [
        FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1"),
        ]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  assert(result)
  print(schedule)
  assert(schedule[0].actualattendees==["paul","noah"])
  # assert(schedule['actualattendees'][0]==["paul","noah"])

def test_optional_fixed():
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=2))
        ]
  fixies = [
        FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1"),
        FixedMeeting(attendees=["noah"],start=mt(0),length=td(hours=2),id="b2",is_optional=True,priority=1)
        ]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  print(schedule,unschedueled_ids)
  assert(result)
  assert([m.start for m in schedule if m.id=="m1"]==[mt(0)])
  # assert(unschedueled_ids==['b2'])
  # assert(schedule[schedule['meetingid']=='b2']['time'].tolist() == ["unscheduled"])
  # print(schedule)
  # schedule, unschedueled_ids = from_meetings_df(schedule,basetime,grain=60*60)
  # print(schedule)

def test_optional_fixed2():
  """optional fixed that can be respected..."""
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(8), id="m1", length=td(hours=2)),
        FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=2))
        ]
  fixies = [
        FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1"),
        FixedMeeting(attendees=["noah"],start=mt(0),length=td(hours=2),id="b2",is_optional=True,priority=1)
        ]
  result, schedule, unschedueled_ids, result_code = solver(floaties,fixies,now,basetime)
  assert(result)
  assert(all([m.start>=mt(2) for m in schedule]))
  # assert(unschedueled_ids == [])
  # assert(schedule[schedule['meetingid']=='b2']['time'].tolist() != ["unscheduled"])
  print(schedule)
  # print(schedule)
  # schedule, unschedueled_ids = from_meetings_df(schedule,basetime,grain=60*60)
  # print(schedule)

