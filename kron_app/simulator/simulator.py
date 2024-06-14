from collections import defaultdict
# import copy
import pickle
import numpy as np
import math
import os
from datetime import datetime, timedelta
from sqlalchemy_utils import database_exists, create_database, drop_database
from kron_app.models import User, Event, EventState, Calendar, FixedEvent, Change, SolverLog
from uuid import uuid4
from kron_app.run_solver import run_solver
from kron_app.utils import from_utc


"""
simulate user events coming in, and run_solver being called to create a schedule.

first generate the equence of simulator events, then play back this sequence with solver calls.

simulator events are one of:
- create a user
- add kronduty fixedevents
- add regular fixed events for a user
- (in principle delete or change fixed events, but we leave this for now.)
- add floating events to be scheduled
- (in principle delete or modify a floating event, but we leave this our for now.)

FIXME: currently there are no "space creation" simulator events (eg deleting a fixed event, adding a kronduty time). these may yield problems with many floaties, so should test them out.

"""

rng = np.random.default_rng(seed=41)

class SimulatorEvent():

  def __init__(self,type):
    self.type = type

  def execute_db(self):
    raise Exception ("execute_db not implemented")

class SetNow(SimulatorEvent):
  
  now=None

  alltimeused=[]

  def __init__(self,now):
    self.now = now
    super().__init__("SetNow")

  def execute_db(self):
    SetNow.now = self.now
    print(f"set now to {SetNow.now}")

    #freeze daemon:
    drafts=Event.query.filter(Event.state == EventState.SCHEDULED).all()
    drafts=[d for d in drafts if d.draft_start<=(SetNow.now+d.freeze_horizon) ]
    # .filter(Event.draft_start<(self.now+Event.freeze_horizon))
    for d in drafts:
      print(f"  freezing event {d.id}")
      for aid in d.attendees:
        a_user=User.query.get(aid)
        e=FixedEvent()
        e.calendar = a_user.calendars[0]
        e.all_day = False
        e.start_dt = d.draft_start
        e.end_dt = d.draft_end
        e.uid = uuid4()
        db.session.add(e)
      db.session.delete(d)
      db.session.commit()

    #remove stale unscheduled events (eg from repair):
    #TODO: i'm not sure the live system clears out stale unscheduled events, though it should...
    unsched=Event.query.filter(Event.state == EventState.UNSCHEDULED).all()
    unsched=[d for d in unsched if SetNow.now+d.freeze_horizon>d.window_end-d.length]
    for d in unsched:
      print(f"  removing stale event {d.id}")
      db.session.delete(d)
      db.session.commit()
    
    for u in User.query.all():
      print(f"  user {u.id} has mean {busyness(u.id)/3600}hrs/day busy")
    # #find the business of each user for the next week
    # for u in User.query.all():
    #   fe = FixedEvent.query.filter_by(kron_duty=False)\
    #         .join(FixedEvent.calendar) \
    #         .filter((SetNow.now<FixedEvent.end_dt), (SetNow.now+timedelta(days=7)>FixedEvent.start_dt)) \
    #         .filter(Calendar.user_id==u.id) \
    #         .all()      
    #   de = Event.query.filter(Event.state==EventState.SCHEDULED) \
    #           .filter(Event.attendees.overlap([u.id])) \
    #           .filter((SetNow.now<Event.draft_start), (SetNow.now+timedelta(days=7)>Event.draft_start)).all()

    #   time_used=sum([e.end_dt-e.start_dt for e in fe],timedelta(hours=0)) \
    #     + sum([e.length for e in de],timedelta(hours=0))

    #   SetNow.alltimeused.append({'user':u.id,'time_used':time_used,'now':SetNow.now})
    #   print(f"  user {u.id}, time used {time_used} over next week ({len(fe)} fixed, {len(de)} draft events)")


    # print(f"events left: {[f'event {e.id}, {e.state_name}' for e in Event.query.all()]}")

class AddUser(SimulatorEvent):

  user_count=0

  def __init__(self,name):
    self.email = 'user'+name+'@kronistic.com'
    self.id = AddUser.user_count
    AddUser.user_count += 1
    super().__init__("AddUser")

  def execute_db(self):
    # print(f"run execute_db user {self.email}, existing: {User.query.all()}")
    u = User()
    u.email = self.email
    u.name=self.email
    self.user_db=u
    c = Calendar()
    c.user = u
    c.gcal_id = uuid4()
    print(f"  added user {u}")
    db.session.add(u,c)
    db.session.commit()
    return u

class AddKronduty(SimulatorEvent):

  def __init__(self, creator, start_at, length, priority=None):
    self.creator = creator
    self.start_at = start_at
    self.length = length
    self.priority = priority
    super().__init__("AddKronduty")

  def execute_db(self):
    k = FixedEvent()
    k.calendar = self.creator.user_db.calendars[0]
    k.all_day = False
    k.start_dt = self.start_at
    k.end_dt = self.start_at + self.length
    k.uid = uuid4()
    k.kron_duty = True
    k.priority = self.priority
    k.dirty = True
    print(f"  added Kronduty, creator={self.creator.user_db}, start={k.start_dt}, end={k.end_dt}, priority={k.priority}")
    db.session.add(k)
    db.session.commit()
    return k

class AddFixedEvent(SimulatorEvent):
  def __init__(self, creator, start_at, length):
    self.start_at = start_at
    self.length = length
    self.creator = creator
    super().__init__("AddFixedEvent")

  def execute_db(self):
    k = FixedEvent()
    k.calendar = self.creator.user_db.calendars[0]
    k.all_day = False
    k.start_dt = self.start_at
    k.end_dt = self.start_at + self.length
    k.uid = uuid4()
    k.kron_duty = False
    k.dirty = True
    print(f"  added FixedEvent, creator={self.creator.user_db}, start={k.start_dt}, end={k.end_dt}")
    db.session.add(k)
    db.session.commit()
    return k

class AddFloatEvent(SimulatorEvent):
  def __init__(self, creator, length, wstart, wlength, attendees, optionalattendees=[], freeze_horizon=timedelta(days=1)):
    self.creator = creator
    self.length = length
    self.wstart = wstart
    self.wlength = wlength
    self.attendees = attendees
    self.optionalattendees = optionalattendees
    self.freeze_horizon = freeze_horizon
    super().__init__("AddFloatEvent")

  def execute_db(self):
    tzname=self.creator.user_db.tzname
    e = Event()
    e.length = self.length
    e.window_start = self.wstart
    e.window_end = self.wstart + self.wlength
    e.window_start_local = e.window_start #TODO: need from UTC?
    e.window_end_local = e.window_end #TODO: need from UTC?
    e.freeze_horizon = self.freeze_horizon
    e.attendees = [a.user_db.id for a in self.attendees]
    e.optionalattendees= [a.user_db.id for a in self.optionalattendees]
    e.dirty = True
    e.creator = self.creator.user_db
    e.tzname = e.creator.tzname
    print(f"  added Event {e.id}, creator={e.creator}, length={e.length}, wstart={e.window_start}, wend={e.window_end}, attendees={e.attendees}")
    db.session.add(e)
    db.session.commit()
    return e

#####distributions and distribution params used in sim:
alpha=0.8 #pseudocounts for a person to be in a meeting
alpha_fixedevents=0.8 #pseudocounts for a person to have a fixed meeting
# decay_rate=0.85 #rate at which meeting counts are decayed on each time_step. 
# alpha=0.2 #underlying prob of choosing a person to be in a meeting
# alpha_fixedevents=0.2 #underlying prob of choosing a person to have a fixed meeting
# decay_rate=0.95 #rate at which meeting counts are decayed on each time_step. 
default_kronduty_prob=0 #turned off default because they are PT but i did the kronduty in UTC
prob_fixed_event=0.6 #maybe we need to simulate different scenarios with different kron usage..

def random_start(now):
  """distribution on fixedevent start times (from now).
  draw a 15min bin from a poisson peaked two days from now...
  FIXME: is this a sensible distribution??"""
  p=rng.poisson(24*4*2)+1
  return now+p*timedelta(minutes=15)

def random_wstart(now):
  """distribution on event window start times (from now).
  draw a 1day bin from a poisson peaked tomorrow...
  FIXME: is this a sensible distribution? might want heavier left tail."""
  p=rng.poisson(1)+1
  return now+p*timedelta(days=1)

def length_dist():
  """distribution on event / fixedevent lengths, in 15min chunks"""
  p=np.array([0.1, 0.4, 0.2, 0.3, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1, 0.15])
  p=p/float(sum(p))
  n=rng.choice(len(p),p=p)
  return (n+1)*timedelta(minutes=15)

def w_length_dist():
  """distribution on event window lengths, multiple of days.. peak at 1wk"""
  p=np.array([0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 1.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.3, 0.1, 0.1, 0.1, 0.1, 0.1])
  p=p/float(sum(p))
  n=rng.choice(len(p),p=p)
  return (n+1)*timedelta(days=1)

def attendees_dist():
  """distribution on number of attendees in a meeting... 
  FIXME: probably should be something heavy tailed? get from empirical distr."""
  p=np.array([5, 2, 2, 1, 1, 1, 1])
  p=p/float(sum(p))
  n=rng.choice(len(p),p=p)
  n=n+2 #at least 2 people in a meeting..
  return rng.integers(2,5)

def flip(p):
  return rng.random()<p

def build_sim(num_users=10,basetime=datetime(2022,6,15), sim_time=timedelta(days=21), time_step=timedelta(days=1), meetings_per_user_per_timestep=1):

  meetings_per_timestep=num_users*meetings_per_user_per_timestep
  sim_seq=[]
  users=[]
  now=basetime
  sim_seq.append(SetNow(now))

  ####add users. for now we add all of them at the start.
  for i in range(num_users):
    # print(f"sim_seq user {i}")
    u=AddUser(str(i))
    users.append(u)
    sim_seq.append(u)

  ####for each user set up kronduty times. some users are left to default, others have @kron events.
  #   some users have @kron if needed events. 
  #   for simplicity all @kron events are repeating, and we unpack out to max_time
  for u in users:
    #with some prob make @kron times (not default)
    if flip(1-default_kronduty_prob):
      #make chunks of (not) available time filling up 8a-6p
      #TODO: users with different timezones?
      duty=[]
      x=timedelta(hours=8)
      while x<timedelta(hours=18):
        p=np.array([0.3, 0.6, 0.2, 0.6, 0.2, 0.5, 0.2, 0.5])
        p=p/float(sum(p))
        n=rng.choice(p.size,p=p)
        length = (n+1)*timedelta(minutes=30)
        priorities = [-1, None, 1, 2, 3] #-1 means don't creat a kronduty
        priority_probs =  np.array([0.2, 0.7, 0.3, 0.1, 0.1]) 
        priority = priorities[rng.choice(priority_probs.size,p=priority_probs/float(sum(priority_probs)))]
        if priority != -1:
          duty.append(AddKronduty(u,basetime+x,length,priority))
        x= x+length

      print(f"user {u.email} kronduty starts:")
      for d in duty: print(f"  {d.start_at} -- {d.start_at+d.length}, {d.priority}")

      #replicate the kronduty events for every weekday and every week out to max_time
      #TODO: since we create events beyond sim_time we might want to go out farther?
      for d in range(2*math.ceil(sim_time.total_seconds()/time_step.total_seconds())):
        #don't copy on weekends:
        if d%7!=5 and d%7!=6:
          for e in duty:
            sim_seq.append(AddKronduty(e.creator,e.start_at+d*time_step,e.length,priority=e.priority))

  ####now repeatedly choose a user and create an event or a fixedevent

  #we keep track of the matrix of how many times each pair of users has met (with decay),
  # each row and column is labeled by a user
  pairwise_meeting_counts = np.ones([AddUser.user_count,AddUser.user_count])*alpha
  fixed_event_counts = np.ones([AddUser.user_count])*alpha_fixedevents

  while now < basetime+sim_time:
    #update time
    now = now + time_step
    sim_seq.append(SetNow(now))
    # #decay meeting counts
    # pairwise_meeting_counts *= decay_rate
    # fixed_event_counts *= decay_rate

    for _ in range(meetings_per_timestep):

      #if we decide to create a fixedevent, we simply choose a random start time and length.
      if flip(prob_fixed_event):
        #choose the meeting creator. choosing in proportion to meeting count leads to a power law on meeting creation.
        # user_mtg_counts = fixed_event_counts + alpha_fixedevents
        uid = rng.choice(AddUser.user_count,p=fixed_event_counts/float(sum(fixed_event_counts)))
        u=users[uid]
        start_at = random_start(now)
        length = length_dist()
        sim_seq.append(AddFixedEvent(u,start_at,length))
        #update counts:
        fixed_event_counts[uid] += 1
      else:
        """
        if we decide to create a float event, we choose a random length and window. 
        we also have to choose attendees and we want to end up with a graph with the right "clumpiness"
        we thus choose attendees based on:
         the number of attendees is drawn from an empirical distribution,
         prob of adding a user as next attendee is propto alpha + the number of times user 
         has met with users already in meeting (with time decay)
        we probably want a power law on user meeting counts, to do that we could:
          vary alpha per user (some users meet with more others), or,
          add preferential attatchment: prob of adding user is propto number of meetings user is in 
          (plus number of meetings user is in with existing users).
        TODO: we may want to truncate number of meetings per user?
        TODO: add something like "group meetings" that have a lot of attendees mostly optional
        TODO: recurring meetings? (might not be worth it to simulate.)
        TODO: create optional meetings?
        TODO: sample freeze horizon? currently always 1 day.
        """
        length = length_dist()
        wstart = random_wstart(now)
        wlength = w_length_dist()
        num_attendees = min(attendees_dist(),num_users)
        attendees = []
        #TODO: optional attendees?
        for i in range(num_attendees):
          #get counts of attendees meeting with each user, and user meeting counts
          counts = np.diagonal(pairwise_meeting_counts)
          # counts = counts + alpha
          for a in attendees:
            counts = counts + pairwise_meeting_counts[a.id]
          for a in attendees:
            #can't choose someone already in meeting!
            counts[a.id] = 0
          new_att_id = rng.choice(AddUser.user_count,p=counts/float(sum(counts)))
          attendees.append(users[new_att_id])

        #note first attendee is made the creator
        sim_seq.append(AddFloatEvent(attendees[0], length, wstart, wlength, attendees))

        #update counts
        for u in attendees:
          for v in attendees:
            pairwise_meeting_counts[u.id][v.id] += 1

    #note that we'll rely on repair to deal with meetings that can't be scheduled as requested. 
    # keep track of how often this happens so it doesn't get out of hand...?
    # (eg a power law on per user meeting counts isn't quite right, since a person can only have so many meetings!)

  return sim_seq

# def remove_users(sim_seq: List[SimulatorEvent], users):
#   """for testing purposes we might want the same sim but with certain users removed. 
#   users is list of user ids to remeove"""
#   new_sim=[]
#   for e in sim_seq:
#     if e.type == "AddUser" and e.id in users:
#       pass
#     elif (e.type=="AddKronduty" or e.type=="AddFixedEvent") and e.creator.id in users:
#       pass
#     elif e.type=="AddFloatEvent":
#       #remove if creator is in users list, otherwise remove any attendees in list
#       if  e.creator.id not in users:
#         f = copy.deepcopy(e)
#         f.attendees = [a for a in e.attendees if a.id not in users]
#         f.optionalattendees = [a for a in e.optionalattendees if a.id not in users]
#         new_sim.append(f)
#     else:
#       new_sim.append(e)
  
#   return new_sim

"""
Execute the simulator actions in order.
"""
from kron_app import db

def run(sim_seq):
  #make the db
  username = os.environ.get('POSTGRES_USERNAME') or ''
  password = os.environ.get('POSTGRES_PASSWORD') or ''
  host = 'localhost'
  port = 5432
  url = f'postgresql://{username}:{password}@{host}:{port}/kron-sim'
  if database_exists(url):
    #this can happen when simulator hits an error and doesn't drop db
    db.drop_all()
    drop_database(url)
  create_database(url)
  db.create_all()

  #run the steps
  for s in sim_seq:
    print(f"executing db action {s.type}")
    s.execute_db()

    tosync, emails = run_solver(now=SetNow.now)
    if len(emails)>0:
      print(emails)

    
  #rely on logging to capture stats we want into SolverLog.
  runs = SolverLog.query.all()
  runs = [r.data for r in runs]
  runtimes = [r['cputime'] for r in runs if not r['repair']]
  repairtimes = [r['cputime'] for r in runs if r['repair']]

  print(runtimes)
  print([r['problem_size'] for r in runs if not r['repair']])
  print(f"total solver time {sum(runtimes)+sum(repairtimes)}")
  print(f"**runtime mean {np.mean(runtimes)}, std {np.std(runtimes)}, median {np.median(runtimes)}")
  print(f"**repair was called {len(repairtimes)} times, took mean {np.mean(repairtimes)}.")

  #save solver log to file for later analysis:
  with open('solver_log.pickle', 'wb') as handle:
    pickle.dump(runs, handle, protocol=pickle.HIGHEST_PROTOCOL)

  # to load from the log file:
  #   b = pickle.load(open('solver_log.pickle', 'rb'))

  #save time usage stats to file:
  timeuse=[busyness(u.id) for u in User.query.all()]
  with open('time_usage.pickle', 'wb') as handle:
    pickle.dump(timeuse, handle, protocol=pickle.HIGHEST_PROTOCOL)

  #close the db
  db.session.close()
  db.drop_all()
  drop_database(url)


# Average of daily total calendar entry lengths, for period spanned by
# calendar entries. (In seconds.) Overlaps ignored, so daily total can
# be > 24 hours, though this won't happen in simulator.
def busyness(user_id):
  d = defaultdict(int)
  fs = FixedEvent.query \
                  .join(FixedEvent.calendar) \
                  .filter(Calendar.user_id==user_id,
                          FixedEvent.kron_duty==False) \
                  .all()
  if len(fs)==0:
    return 0.
  for f in fs:
    start_at, end_at = f.start_at, f.end_at
    d[start_at.date()] += int((end_at-start_at).total_seconds())
  dates = d.keys()
  daytotals = d.values()
  days_spanned = (max(dates)-min(dates)).days + 1
  return float(sum(daytotals))/days_spanned

if __name__ == '__main__':
  run(build_sim(num_users=5,sim_time=timedelta(days=2),meetings_per_user_per_timestep=5))

