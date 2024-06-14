import pysmt.shortcuts as ps
from typing import Optional, List
from datetime import datetime
from kron_app.solver.utils import Time, constant, make_meetings, make_drafts, FloatMeeting, FixedMeeting, DraftMeeting
from kron_app.utils import dictunion

#pysmt encodings:
sat = True
unsat = False

#
# need to setup z3 paths:
#
# export PYTHONPATH=~/z3/bin/python
# export DYLD_LIBRARY_PATH=$DYLD_LIBRARY_PATH:~/z3/bin 
#
# i think pysmt can do this for you, but i didn't  


#simple solver core using pysmt wrappers.
#solver expects a dataframe, can use utils make_meetings_df to get it.
#return: the sat result and the meetings df with 'time'column for scheduled time interval
#
# Note: busy times and float meetings are both in the meetings list, 
#  fixed meetings have a time innterval while floats don't. float meetings also have a 'window' for scheduling. 
#  with this encoding avoiding busy times is the same as avoiding conflicts.
#  FIXME: this means the semantics of soft busy constraints is a little odd: once one meeting is scheduled then 
#           they are taken as being "not scheduled" and further conflicts with that time are fine...
#           could work around this by breaking up busy blocks into separate chunks?
#
# Note: there is no max planning horizon, but all events must fall in their finite window.
#
# TODO: handle locations
# TODO: add solver hints, such as time-available>time-required constraints?

#The ontology here consists of: 
#  people, sets of people with some members optionally included, 
#  times, time intervals that can exist or not (for optionality),
#  locations, location set in which one is the actual location


#simple helper class for time intervals:
class Interval:
  def __init__(self, start, length, optional=False, name="interval"):
    self.start = constant(start) if isinstance(start, (int, float)) else start 
    self.end = self.start + (constant(length) if isinstance(length, (int, float)) else length) 
    self.exist = ps.Bool(True) if not optional else ps.Symbol(name+"exist") 

  def __str__(self):
  	return "(% s, % s)" % (self.start,self.end) if self.exist else "unscheduled"

  def empty_intersect(self, other):
    #check if interection of self with other is empty
    #  this happens if one interval ends before other starts
    #  or either interval doesn't exist
    return ps.Or(ps.Not(self.exist),ps.Not(other.exist), 
                  self.end <= other.start, other.end <= self.start)

  def contains(self, other):
    #check if self fully contains other, or either doesn't exist.
    return ps.Or(ps.Not(self.exist),ps.Not(other.exist), 
                ps.And( ps.LE(self.start,other.start), ps.GE(self.end,other.end)))

  def make_concrete(self,model):
    self.exist = self.exist if isinstance(self.exist, bool) else  model.get_py_value(self.exist) #python_num(model[self.exist])
    if self.exist:
      self.start = self.start if isinstance(self.start, (int, float)) else model.get_py_value(self.start) #python_num(model.eval(self.start))
      self.end = self.end if isinstance(self.end, (int, float)) else model.get_py_value(self.end) #python_num(model.eval((self.end)))
      return [self.start, self.end]
    else:	
      return "unscheduled"

class Set:
  def __init__(self, fixedelts, optionalelts=[], name="set"):
    #convert into dict of key = elt, val = bool inclusion indicator
    self.elts = dictunion({e:ps.Bool(True) for e in fixedelts}, {e:ps.Symbol(e+name+"included") for e in optionalelts})

  def __str__(self):
    return str(self.elts)

  def any_intersect(self, other):
    tmp = [ps.And(v,other.elts[k]) for k,v in self.elts.items() if k in other.elts]
    return ps.Bool(False) if len(tmp) == 0 else ps.Or(tmp)

  #check if the two sets could ever have an intersection, based on support sets
  def could_intersect(self, other):
    return set(self.elts.keys()) & set(other.elts.keys())

  #return the number of set elements that are included
  #FIXME: don't count non-optional?
  def count(self):
    return sum(ps.Ite(v,constant(1),constant(0)) for v in self.elts.values())

  def make_concrete(self,model):
    # self.elts = {k: (v if isinstance(v,bool) else python_num(model[v])) for k,v in self.elts.items()}
    # self.elts = {k: model.get_py_value(v) for k,v in self.elts.items()}
    self.elts = [k for k,v in self.elts.items() if model.get_py_value(v)]
    return self.elts

def make_window(row):
  #if fixed meeting use actual time as window interval
  #TODO: this is only used for float now, so can simplify
  start = row['window_start'] if not row['is_fixed'] else row['start']
  length = row['window_end']-row['window_start'] if not row['is_fixed'] else row['length']
  return Interval(start, length, name=row['id']+"window")

def make_time(row):
  start = row['start'] if row['is_fixed'] else ps.Symbol(row['id']+"start", Time)
  return Interval(start, row['length'], optional= row['is_optional'], name=row['id'])

def make_attendees(row):
  return Set(row['attendees'],row['optionalattendees'],name=row['id'])

def get_constraints(floaties,fixies):
  #constraint that meeting occurs in its time window:  
  a=[]
  for r in floaties:
    a.append(r['window'].contains(r['time']))

  #fundemental schedule axiom: 
  #  forall meeting:m1 forall meeting:m2 intersect(attendees(m1), attendees(m2)) => not intersect(time(m1),time(m2))
  # note that empty_intersect will be true if either meeting doesn't exist (isn't going to be scheduled).
  for r in floaties:
    for s in fixies:
      if r['actualattendees'].could_intersect(s['actualattendees']): 
        ax = ps.Implies(r['actualattendees'].any_intersect(s['actualattendees']), 
                        r['time'].empty_intersect(s['time']) )
        a.append(ax)

  for r in floaties:
    for s in floaties:
      if r==s: break
      if r['actualattendees'].could_intersect(s['actualattendees']): 
        ax = ps.Implies(r['actualattendees'].any_intersect(s['actualattendees']), 
                        r['time'].empty_intersect(s['time']) )
        a.append(ax)

  return a

def kron_solver(floaties, fixies, config = {'nogaps': False}):

  users = set(sum([m.attendees+m.optionalattendees for m in floaties+fixies],[]))
  # users = set([u for a in meetings_df['attendees'].tolist()+meetings_df['optionalattendees'].tolist() for u in a])
  print(f"all users: {users}")

  #For now convert objects into dicts so we can add new fields.. eventually extend objects?
  floaties=[m.dict() for m in floaties]
  fixies=[m.dict() for m in fixies]

  with ps.Solver(name="z3") as solver:

    #convert window to internal Interval class
    for m in floaties: m['window']=make_window(m)

    #add time interval variables for floating meetings to schedule
    for m in floaties+fixies: m['time']=make_time(m)

    #convert attendees into Set class
    for m in floaties+fixies: m['actualattendees'] = make_attendees(m)

    ##setup hard constraints
    a = get_constraints(floaties, fixies)

    ##run the solver (on hard constraints)
    for x in a: solver.add_assertion(x)
    result = solver.solve()

    print(f"result of solve on hard constraints is {result}.")

    if not result:
      return result, None

    #get model, used below to initialize optimization threshold
    mod = solver.get_model()


    ##set up soft constraints
    #TODO switch into feature-based style: 
    #  a bunch of preferences feature functions, computed on individual schedules, then weighted sum

    #FIXME: need to think about balance between optional meetings, optional attendees, and preferences
    #  for the moment i just set some weights

    #soft constraint that optional meetinngs should be scheduled
    optionalmtgs=constant(0)
    for r in floaties+fixies:
      if r['is_optional']:  
        #NOTE: there's a funy 'bug' where Bool*1=Bool, otherwise could do r['time'].exist*r['priority']
        optionalmtgs += ps.Ite(r['time'].exist,constant(r['priority']),constant(0)) 

    #add soft constraint that optional attendees are present
    optionalatt=constant(0)
    for r in floaties+fixies:
      optionalatt += r['actualattendees'].count()

    objective=constant(0)
    objective += 10*optionalmtgs
    objective += 5*optionalatt
    for u in users:
      user_schedule = get_schedule(u,floaties,fixies)
      #TODO: generalize this to wieghted combo of different features...
      if config['nogaps']:
        # objective += nogaps(user_schedule)
        objective += soonermtgs(user_schedule)
      # objective += latermtgs(user_schedule)


    ##soft constraint loop: increase threshold in constraint objective>objthresh until unsat
    #NOTE: currently don't push/pop solver stack since we're always just adding more restrictive constraints.
    objthresh = mod.get_py_value(objective)
    while result:
      #TODO: maybe do something like binary search?
      # solver.push()
      objthresh=objthresh+1 
      solver.add_assertion(objective>= constant(objthresh))
      result = solver.solve()
      if result==sat: 
        #save bets model so far:
        mod = solver.get_model()
      print(f" soft objective thresh {objthresh}, result {result}")
      # print(f"meeting {r['id']} with {r['actualattendees'].elts.keys()}, number of optional attendees left out: {r['actualattendees'].count_leftout()}")
      #FIXME catch timeout (result unknown) and try to find out if it gets sat again later?
      # solver.pop()		

    ##make times concrete
    for m in floaties:
      m['time'] = m['time'].make_concrete(mod)
      m['window'] = m['window'].make_concrete(mod)
      m['actualattendees'] = m['actualattendees'].make_concrete(mod)

    return True, floaties


###user schedule will be a list of meetings that the user is / mmight be a part of
def get_schedule(user,floaties,fixies):
  return [m for m in floaties+fixies if user in m['attendees'] or user in m['optionalattendees']]

###schedule features:

#fragmentation: no gap between a floaty and the meeting before.
def nogaps(user_schedule):
  objective=constant(0)
  # print(f"user_schedule {user_schedule}")
  for meeting in user_schedule:
    if not meeting['is_fixed']:
      #FIXME: we probably don't want to include the off-duty / on-duty-if-needed events as neighbors
      #  since that would result in trying to schedule meetings near them...
      #FIXME: can narrow this based on windows
      possible_prior_mtgs = user_schedule 

      #does closest meeting end when this one starts?
      any_right_before = ps.Or(ps.And(m['time'].exist, ps.Equals(meeting['time'].start,m['time'].end)) for m in possible_prior_mtgs)

      objective += ps.Ite(any_right_before, constant(1), constant(0))

  return objective

#make meetings be sooner or later. this is mostly for testing.
def soonermtgs(user_schedule):
  objective=constant(0)
  for meeting in user_schedule:
    if not meeting['is_fixed']:
      objective += meeting['window'].end-meeting['time'].start
  return objective
# def latermtgs(user_schedule):
#   objective=constant(0)
#   for meeting in user_schedule:
#     objective += meeting['time'].start-meeting['window'].start
#   return objective


####### main entry point to solver
#it's messy to let external things interact with the meetings_df, so this wrapper handles all that
def solver(floaties : List[FloatMeeting], fixies : List[FixedMeeting], now : datetime, grain : int =900, config = {'nogaps': False}):
  """now indicates the current time and is used for make=ing sure meetings aren't scheduled
  sooner than their freeze horizon"""  
  #we use earliest meeting window as basetime (internal 0). 
  #  this can be anything but it's convenient to tie it to the problem.
  #FIXME: basetime needs to be on grain-grid. this is usually so for window_start but not guaranteed.
  if len(floaties)==0:
    return True,[],[]
  basetime = min([m.window_start for m in floaties])
  floaties, fixies = make_meetings(floaties,fixies,basetime,now,grain=grain)
  result, schedule_floaties = kron_solver(floaties,fixies,config = config)
  if result==sat:
    schedule, unschedueled_ids = make_drafts(schedule_floaties,basetime,grain=grain)
    return True, schedule, unschedueled_ids
  else:
    return False,None,None


# if __name__ == '__main__':
