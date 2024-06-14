# import pandas as pd
import random, math, statistics
from solver import solver
from solver_z3_ordering import solver as solver_z3_ordering
import time
from datetime import datetime, timedelta
from utils import FloatMeeting, FixedMeeting, DraftMeeting

# Monte Carlo testing for kron solver

# TODO: make process (roughly) exchangeable wrt order of people? eg use indian buffet process...
# TODO: add optional events and optional attendees.
# TODO: generate unsat problems (how? maybe keep adding meetings with a given attendee and window until required meetingtime exceeds window?)

# #simple helper class for time intervals:
# class Interval:
#   def __init__(self, interval, optional=False, name="interval"):
#     self.start = interval[0]
#     self.end = interval[1]
#     # self.exist = True if not optional else z3.Bool(name+"exist")

#   def __repr__(self):
#     return "(% s, % s)" % (self.start,self.end)

#   def empty_intersect(self, other):
#     #check if interection of self with other is empty
#     #  this happens if one interval ends before other starts
#     # return z3.Or(z3.Not(self.exist),z3.Not(other.exist), self.end < other.start, other.end < self.start)
#     return (self.end < other.start) or (other.end < self.start)

#   def contains(self, other):
#     #check if self fully contains other.
#     return (self.start<=other.start) and (self.end>=other.end)

#   def __len__(self):
#     return self.end - self.start +1


def flip(w=0.5):
  return random.random() < w

class Gensym:
  def __init__(self,stem):
    self.g = 0
    self.stem = stem
  def __call__(self):
    self.g=self.g+1
    return self.stem+str(self.g)

#intersection test between two meetings (either draft or fixed)
def intersect(a,b):
  return not (a.end<b.start or b.end<a.start)

def randtime(start, end):
  basetime=datetime(2022,4,1)
  grain=60*15
  roundstart=basetime+timedelta(seconds=math.ceil((start-basetime).total_seconds()/grain)*grain)
  roundend=basetime+timedelta(seconds=math.floor((end-basetime).total_seconds()/grain)*grain)
  # start-timedelta(minutes=start.minute%15,seconds=start.second,microseconds=start.microsecond)
  num_times=1+(roundend-roundstart)//timedelta(seconds=grain)
  return roundstart + timedelta(seconds=grain)*random.choice(range(num_times))
  # range_seconds = (end-start).total_seconds()
  # return start + timedelta(seconds=random.randint(0,range_seconds)) #CHECKME: endpoints?

now = datetime(2022,4,13,hour=10,minute=12)

# beta = prob of adding user to an existing meeting, if possible
# alpha = prob of making a new meeting be a float
# gamma = prob of a new meeting being optional
def sample_problem(users, total_length=timedelta(days=14), beta=0.5, alpha=0.5, gamma=0.0, num_meetings_per_user=10):
  floatm = Gensym("meet")
  fixedm = Gensym("busy")

  #init fixed meetings with dummy start and end event
  fixies=[FixedMeeting(attendees=users, id=fixedm(), start=now, length=timedelta(0)),
  FixedMeeting(attendees=users, id=fixedm(), start=now+total_length, length=timedelta(0))]

  #floaties will be a list of DraftMeetings
  floaties=[]

  for user in users:

    #TODO: add on-duty times?

    #try to add N meetings for this user, not all attemps will 'work' so number of meetings will be <=N
    for i in range(num_meetings_per_user):
      current_schedule = [m for m in fixies+floaties if user in m.attendees]
      #candidate events to add this user to:
      candidates = [m for m in floaties if not any(intersect(m,n) for n in current_schedule)]
      if len(candidates)>0 and flip(beta):
        #add user to existing float event that fits in their schedule.
        m=random.choice(candidates)
        m.attendees.append(user)
      else:
        #make a new event that this user attends, decide if it's float or fixed
        #to find a time, sort current schedule by start time, then choose an element to insert after
        current_schedule.sort(key=lambda m: m.start)
        min_mtg_length=timedelta(minutes=15)
        indices = [i for i in range(len(current_schedule)-1) if current_schedule[i].end+min_mtg_length<=current_schedule[i+1].start]
        if len(indices)>0:
          idx = random.choice(indices)
          #range where new meeting can go
          startrange = current_schedule[idx].end
          endrange = current_schedule[idx+1].start
          #choose an interval in between,
          #first choose a meeting length (no bigger than range) from plausible distr.
          lengthdist = [[min_mtg_length, 0.05],
                        [timedelta(minutes=30), 0.4], 
                        [timedelta(minutes=45), 0.2],
                        [timedelta(minutes=60), 0.2],
                        [timedelta(minutes=90), 0.1],
                        [timedelta(minutes=120), 0.05]]
          lengthdist=[l for l in lengthdist if l[0]<=endrange-startrange]
          length=random.choices([l[0] for l in lengthdist], weights=[l[1] for l in lengthdist])[0]
          #then place the meeting uniformly in the interval (but on grid)
          start=randtime(startrange,endrange-length)
          end=start+length
          start in [m.start for m in current_schedule]
          # print(f"  start: {start-now}, end: {end-now}")
          # print(f"   range {endrange-startrange}, before {start-startrange}, length {end-start}, after {endrange-end}")
          # assert(start>=startrange)
          # assert(end<=endrange)
          is_optional=flip(gamma)
          priority=random.choices([1,2,3], weights=[0.5,0.25,0.25])[0]
          if flip(alpha):
            floaties.append(DraftMeeting(attendees=[user],id=floatm(),start=start,end=end,window_start=start,window_end=end,length=end-start,actualattendees=[user],is_optional=is_optional,priority=priority))
          else:
            fixies.append(FixedMeeting(attendees=[user],id=fixedm(),start=start,length=end-start,is_optional=is_optional,priority=priority))

  fixies = fixies[2:] #take off dummy events

  #turn schedule into satisfiable scheduling problem by adding random windows for the float meetings, but strip the times
  #FIXME: use a more realistic distribution of window times...
  for m in floaties:
    m.window_start = randtime(now, m.start)
    m.window_end = randtime(m.end, now+total_length)

  return floaties, fixies

if __name__ == '__main__':

  random.seed(1)
  
  for i in range(1):

    num_users=5
    u = Gensym("user")
    users=[u() for i in range(num_users)]
    total_length=timedelta(days=3)
    floaties,fixies = sample_problem(users=users,num_meetings_per_user=70,total_length=total_length, alpha=0.2, gamma=0.2)
    # meetings = make_meetings_df(meetings)

    print(f"generated {len(floaties)+len(fixies)} meetings for {num_users} users ({len(floaties)} FloatMeetings, {len([f for f in floaties if f.is_optional])} optional, and {len(fixies)} FixedMeetings, {len([f for f in fixies if f.is_optional])} optional).")

    #per user schedule stats:
    used_ratio=[]
    for u in users:
      used_time = sum([m.length for m in floaties+fixies if u in m.attendees],timedelta(0))
      used_ratio.append(used_time / total_length)
    print(f"  average {statistics.mean(used_ratio)*100}% of total time used.")
    # print(f"  user {u} used {used_ratio*100}% of total time")

    # stats = pd.DataFrame()
    # stats['float_meetings'] = [sum(meetings['time']=="none")]
    # stats['fixed_meetings'] = [sum(meetings['window']=="none")]
    # stats['people_per_meeting'] = [meetings[meetings['time']=="none"]['attendees'].apply(len).mean()]
    # # stats['meetings_per_user'] = [ u in meetings[''] for u in users]

    #TODO:store mean meetings per user, other stats?

    # t = time.process_time()
    # result, schedule, unschedueled_ids = solver_z3_optimize(floaties,fixies,now, config={"nogaps":False, "timeout": 10000})
    # # print(schedule)
    # elapsed_time = time.process_time() - t
    # assert(result)#because sample_problem should only generate sat problems.
    # print("**z3_optimize solver took "+str(elapsed_time)+" ")

    t = time.process_time()
    result, schedule, unschedueled_ids = solver(floaties,fixies,now, config={'timeout': 10000})
    elapsed_time = time.process_time() - t
    assert(result)#because sample_problem should only generate sat problems.
    print("**standard solver took "+str(elapsed_time)+" ")


    # t = time.process_time()
    # result, schedule, unschedueled_ids = solver_z3_ordering(floaties,fixies,now)
    # elapsed_time = time.process_time() - t
    # assert(result)#because sample_problem should only generate sat problems.
    # print("**ordering based solver took "+str(elapsed_time)+" ")

    # #print out the schedule nicely:
    # ws = min([m.window_start for m in floaties])
    # allthem=fixies+floaties
    # allthem.sort(key=lambda x: x.start)
    # for m in allthem:
    #   if m.is_fixed:
    #     print(f" fixed, {m.id}. start: {m.start-ws}, end: {m.start+m.length-ws}. attendees {m.attendees}")
    #   else:
    #     print(f""" float, {m.id}. start: {m.start-ws}, end: {m.start+m.length-ws} window start: {m.window_start-ws}, window end: {m.window_end-ws}. attendees {m.attendees}""")


    #measure the

    # stats['result'] = [result]
    # stats['runtime'] = [elapsed_time]
   
    # results_df = pd.concat([results_df, stats],ignore_index=True)

  # print(results_df)
  # print(results_df.mean())


