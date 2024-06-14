import pandas as pd
from kron_app.solver.solver import kron_solver, sat
from utils import make_meetings_df, from_meetings_df, FixedMeeting, FloatMeeting

#TODO: do we want to record the soft objective of the found times, to prioritize preferred times?
#TODO: we don't really need to solve from scratch every time...

class Gensym:
  def __init__(self,stem):
    self.g = 0
    self.stem = stem
  def __call__(self):
    self.g=self.g+1
    return self.stem+str(self.g)

def find_possible_times(floaties, fixies, targetmeeting, num_options=5, now=None):

  #FIXME: need to deepcopy fixies and taregtmmeeting to avoid leakage?

  # meetings,_ =make_meetings_df(floaties, fixies)

  #add dummy attendee used for blocking this event from particular times:
  dummy_userid = "dummy"
  targetmeeting.attendees.append(dummy_userid)

  # target_meetingid = targetmeeting.id
  ids = Gensym(str(targetmeeting.id)+"_b")
  # targetmeeting_df,_ =make_meetings_df([targetmeeting],[])

  #times found so far, as "busy" meetings with fixed times
  # times = pd.DataFrame() 
  times = []

  for i in range(num_options):
    #extend base meetings with times and target meeting, then solve
    # meetings_df, basetime =make_meetings_df(floaties,fixies,basetime=now)
    # print(meetings_df)
    # kron_solver(meetings_df)
    # return

    meetings_df, basetime = make_meetings_df(floaties+[targetmeeting],fixies+times,basetime=now)
    # extended = pd.concat([meetings, times, targetmeeting],ignore_index=True)
    result, schedule = kron_solver(meetings_df)

    if result==sat:
      schedule, unschedueled_ids = from_meetings_df(schedule,basetime)
      #extract found time, create a FixedMeeting for it
      target = [m for m in schedule if m.id==targetmeeting.id][0].copy()
      fixy = FixedMeeting(id=ids(), 
                          attendees=[dummy_userid],
                          start=target.start,
                          length=target.end-target.start)
      times.append(fixy)

      # m=schedule[schedule['meetingid']==target_meetingid].copy()
      # #change attendees to a dummy shared with target event so it blocks target but not others: 
      # m['attendees']=[[dummy_userid]]
      # m['window']="none"
      # m['meetingid']=ids()
      # times = pd.concat([times, m],ignore_index=True)
    else:
      #unsat means there are no more possible times
      break

  # times = times['time'].tolist()
  return times


#simple tests:
from datetime import datetime as d
from datetime import timedelta as td
if __name__ == '__main__':

  #make a time util:
  now = d.utcnow()+td(days=0)
  def mt(i):
    return now+td(hours=i)

  floaties=[FloatMeeting(attendees=["noah","paul"], window_start=mt(0),window_end=mt(6), id="m1", length=td(hours=2)),
            FloatMeeting(attendees=["noah","emily"], window_start=mt(0),window_end=mt(6), id="m2", length=td(hours=2))
            ]
  fixies = [FixedMeeting(attendees=["paul"],start=mt(2), length=td(hours=4), id="b1")]
  target = FloatMeeting(attendees=["noah"], window_start=mt(0), window_end=mt(6), id="e1", length=td(hours=1))
  times = find_possible_times(floaties,fixies,target,now=now)
  print(times)

