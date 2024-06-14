############tests
from datetime import datetime as d
from datetime import timedelta as td
from kron_app.solver.utils import FloatMeeting, FixedMeeting
from kron_app.solver.solver import solver, sat, unsat
from kron_app.solver.repair import extend_windows

#make a time util:
now = d(2022,4,13,hour=10,minute=12)
basetime = now.replace(second=0, microsecond=0, minute=0)
def mt(i):
  return basetime+td(hours=i+1)

def test_extend_windows():
  #unsat because there isn't enough time for both meetings
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
      FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=3))
      ]
  fixies = [FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1")]
  result, schedule, _ = solver(floaties,fixies,now)
  assert(result==unsat)
  #now try repair:
  extensions = extend_windows(floaties,fixies,["m2","m1"],now)
  print(extensions)
  assert(extensions=={'m2': td(hours=1)})

def test_extend_windows2():
  #unsat because there isn't enough time for both meetings
  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
      FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(3), id="m2", length=td(hours=3))
      ]
  fixies = [FixedMeeting(attendees=["paul"],start=mt(0), length=td(hours=3), id="b1"),
      FixedMeeting(attendees=["emily"],start=mt(0), length=td(hours=1), id="b2")]
  extensions = extend_windows(floaties,fixies, ["m2","m1"],now)
  print(extensions)
  assert(extensions=={'m1': td(hours=2), 'm2': td(hours=1)})

import pandas as pd
def test_extend_windows3():
  floaties=[FloatMeeting(id='11', attendees=['1'], optionalattendees=[], window_start=d(2022, 4, 1, 6, 0), window_end=d(2022, 4, 1, 8, 0), length=td(minutes=30), priority=None, is_optional=False, is_fixed=False)]
  fixies=[
  FixedMeeting(attendees=['1'], id='56', start=d(2022, 4, 1, 2, 0), length=td(hours=9), priority=None, is_optional=False, is_fixed=True), 
  FixedMeeting(attendees=['1'], id='offduty1', start=d(2022, 3, 30, 0, 0), length=td(hours=8), priority=None, is_optional=False, is_fixed=True), 
  FixedMeeting(attendees=['1'], id='offduty2', start=d(2022, 3, 30, 16, 0), length=td(hours=16), priority=None, is_optional=False, is_fixed=True), 
  FixedMeeting(attendees=['1'], id='offduty3', start=d(2022, 3, 31, 16, 0), length=td(hours=16), priority=None, is_optional=False, is_fixed=True)
  ]
  now=d(2022, 4, 1, 5, 0)
  extensions = extend_windows(floaties,fixies, ["11"],now)
  print(extensions)
  assert(extensions=={'11': td(minutes=210)})

# def test_reduce_meetings():
#   #unsat because there isn't enough time for both meetings
#   floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(4), id="m1", length=td(hours=2)),
#       FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(4), id="m2", length=td(hours=3))
#       ]
#   fixies = [FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1")]
#   meetings_df, internal_now = make_meetings_df(floaties,fixies,basetime,now)
#   result, schedule = kron_solver(meetings_df,internal_now)
#   assert(result==unsat)
#   #now try repair:
#   meetings_df, internal_now = make_meetings_df(floaties,fixies,basetime,now)
#   x = shorten_meetings(meetings_df, ["m2","m1"])
#   print(x)
#   assert(x=={'m1': 1, 'm2': 0, 'b1': 0})

# def test_reduce_meetings2():
#   #unsat because there isn't enough time for both meetings
#   floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(2), id="m1", length=td(hours=2)),
#       FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(2), id="m2", length=td(hours=2))
#       ]
#   fixies = [FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1")]
#   meetings_df, internal_now = make_meetings_df(floaties,fixies,basetime,now)
#   result, schedule = kron_solver(meetings_df,internal_now)
#   assert(result==unsat)
#   #now try repair:
#   meetings_df, internal_now = make_meetings_df(floaties,fixies,basetime,now)
#   x = shorten_meetings(meetings_df, ["m2","m1"])
#   print(x)
#   assert(x=={'m1': 1, 'm2': 1, 'b1': 0})

# def test_reduce_meetings3():
#   #unsat because there isn't enough time for both meetings
#   floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(1), id="m1", length=td(hours=2)),
#       FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(1), id="m2", length=td(hours=2))
#       ]
#   fixies = [FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1")]
#   meetings_df, internal_now = make_meetings_df(floaties,fixies,basetime,now)
#   result, schedule = kron_solver(meetings_df,internal_now)
#   assert(result==unsat)
#   #now try repair:
#   meetings_df, internal_now = make_meetings_df(floaties,fixies,basetime,now)
#   x = shorten_meetings(meetings_df, ["m2","m1"])
#   # print(x)
#   assert(x==False)
