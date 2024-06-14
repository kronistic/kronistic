import z3
from z3 import sat, unsat
import pandas as pd

#
# to run need z3, pandas
# and need to setup z3 paths:
#
# export PYTHONPATH=~/z3/bin/python
# export DYLD_LIBRARY_PATH=$DYLD_LIBRARY_PATH:~/z3/bin   


#simple solver core
#solver expects a dataframme, 
#helper make_meetings_df connverts from a list of dicts, each dict has fields (* means mandatory, otherwise there are defaults):
# *attendees: a list of userids. if this is a busy time, the list will just have one element.
# optionalattendees: list of userids, if any.
# time: a pair of start, end (in now=0 integer accounting). this will be missing / blank for float events.
# window: a pair of start, end (in now=0 integer accounting). this will be missing / blank for fixed busy times.
# minlength: integer minimum meeting length.
# *meetingid: unique id for this meeting.
# priority: non-optional meeting if string or missing, if integer optional meeting with that priority that this be scheduled.
#
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
# TODO: preferred meeting length (if longer than minlength)
# TODO: handle locations
# TODO: add solver hints, such as time-available>time-required constraints?

# TODO: we should make some shared utilities for representing and manipulating users, times, locations...
# TODO: housekeeping: make a class to represent meetings?


#The ontology here consists of: 
#  people, sets of people with some members optionally included, 
#  times, time intervals that can exist or not (for optionality),
#  locations, location set in which one is the actual location



#helper to turn z3 values into python ones
def python_num(v):
  if z3.is_int_value(v):
    return v.as_long()
  if z3.is_algebraic_value(v):
    v = v.approx(2)
  if z3.is_rational_value(v):
    return float(v.numerator_as_long())/float(v.denominator_as_long())
  #else assume bool
  return z3.is_true(v)

#simple helper class for time intervals:
#TODO: could use bitvec to represent sets of times. maybe faster?
class Interval:
  def __init__(self, interval, optional=False, name="interval"):
    self.start = interval[0]
    self.end = interval[1]
    self.exist = True if not optional else z3.Bool(name+"exist")
  # def __str__(self):
  # 	return "(% s, % s)" % (self.start,self.end) if self.exist else "unscheduled"

  def empty_intersect(self, other):
    #check if interection of self with other is empty
    #  this happens if one interval ends before other starts
    #  or either interval doesn't exist
    return z3.Or(z3.Not(self.exist),z3.Not(other.exist), self.end < other.start, other.end < self.start)

  def contains(self, other):
    #check if self fully contains other, or either doesn't exist.
    return z3.Or(z3.Not(self.exist),z3.Not(other.exist), z3.And(self.start<=other.start, self.end>=other.end))

  def make_concrete(self,model):
    self.exist = self.exist if isinstance(self.exist, bool) else python_num(model[self.exist]) #z3.is_true(model[self.exist])
    if self.exist:
      self.start = self.start if isinstance(self.start, (int, float)) else python_num(model.eval(self.start))
      self.end = self.end if isinstance(self.end, (int, float)) else python_num(model.eval((self.end)))
      return [self.start, self.end]
    else:	
      return "unscheduled"


class Set:
  def __init__(self, fixedelts, optionalelts=[]):
    #convert into dict of key = elt, val = bool inclusion indicator
    self.elts = {e:True for e in fixedelts} | {e:z3.Bool(e+"included") for e in optionalelts}

  def any_intersect(self, other):
    tmp = [z3.And(v,other.elts[k]) for k,v in self.elts.items() if k in other.elts]
    return False if len(tmp) == 0 else z3.Or(*tmp)

  #helper to count number of set elts that are not included
  def count_leftout(self):
    c=0
    for k,v in self.elts.items():
      #TODO for effiency if v is True, not in z3 skip..
      c=c+z3.If(v,0,1)
    return c

  def make_concrete(self,model):
    self.elts = {k: (v if isinstance(v,bool) else python_num(model[v])) for k,v in self.elts.items()}
    self.elts = [k for k,v in self.elts.items() if v]
    return self.elts


#helper to check if priority field indicates an optional meeting
def optional(p):
  return isinstance(p, (int,float))

def kron_solver(meetings_df):
  ##setup z3 solver
  solver = z3.Solver()
  # z3.set_param(verbose=20)
  # solver.set("timeout", 30000)
  # solver.set("solver2_timeout", 1000)
  # solver = z3.SolverFor("QF_LIA") 
  # solver = z3.SolverFor("QF_LRA") 
  # solver = z3.SolverFor("QF_RDL") 
  ##setup Sorts
  Time = z3.IntSort()  
  # Time = z3.RealSort()  

  #convert window to internal Interval class
  #  if there's no window assume fixed time and use time field as interval
  meetings_df['window']=meetings_df.apply(lambda r: Interval(r['window']) if isinstance(r['window'],list) else Interval(r['time']), axis=1)

  #convert attendees into Set class
  meetings_df['actualattendees'] = meetings_df.apply(lambda r: Set(r['attendees'],r['optionalattendees']), axis=1)
  
  #add time interval variables for meetings to schedule
  #TODO: currently assume fixed length meeting for minimal time, for preferred time need added time variable
  def maketime(row):
    if isinstance(row['time'],list): 
      #if it already has a fixed time innterval, use that
      time = row['time']
    else:		
      #otherwise make a start and end with free time vars
      length = row['minlength']
      start=z3.Const(row['meetingid']+"start", Time)
      end = start+(length-1)
      time = [start, end]
    return Interval(time, optional= optional(row['priority']), name=row['meetingid'])

  meetings_df['time'] = meetings_df.apply(maketime,axis=1)

  ##setup hard constraints

  #constraint that meeting occurs in its time window
  for i,r in meetings_df.iterrows():
    solver.add(r['window'].contains(r['time']))

  #fundemental schedule axiom: 
  #  forall meeting:m1 forall meeting:m2 intersect(attendees(m1), attendees(m2)) => not intersect(time(m1),time(m2))
  # note that empty_intersect will be true if either meeting doesn't exist (isn't going to be scheduled).
  for i,r in meetings_df.iterrows():
    for j,s in meetings_df.iterrows():
      #it's symmetric so break out inner loop when you get to yourself
      if i==j: break
      solver.add(z3.Implies(r['actualattendees'].any_intersect(s['actualattendees']), 
                            r['time'].empty_intersect(s['time']) ))


  ##run the solver (on hard constraints)
  result = solver.check()

  #TODO fill in these cases
  if result == z3.unsat:
    print("uh-oh, unsat on hard constraints. need to kick off repair workflow...")
    return result, None
  if result == z3.unknown:
    print("oh shit, "+solver.reason_unknown+", need to catch...")
    return result, None


  ##set up soft constraints
  #TODO switch into feature-based style: 
  #  a bunch of preferences feature functions, computed on individual schedules, then weighted sum
  objective=0

  #soft constraint that optional meetinngs should be scheduled
  for i,r in meetings_df.iterrows():
    if optional(r['priority']):  
      #NOTE: there's a funy 'bug' where Bool*1=Bool, otherwise could do r['time'].exist*r['priority']
      objective = objective + z3.If(r['time'].exist,r['priority'],0) 

  #add soft constraint that optional attendees are present
  for i,r in meetings_df.iterrows():
    objective = objective + r['actualattendees'].count_leftout()

  ##soft constraint loop: increase threshold in constraint objective>objthresh until unsat
  objthresh = 0
  while result == z3.sat:
    #TODO: maybe do something like binary search?
    #TODO: can start objthresh at whatever objective value was achieved by previous solver.check()
    solver.push()
    objthresh=objthresh+1 
    solver.add(objective>=objthresh)
    result = solver.check()
    #FIXME catch timeout (result unknown) and try to find out if it gets sat again later?
    solver.pop()		

  #solve once more with best sat threshold
  #TODO: store best model innstead?
  solver.add(objective>=objthresh-1)
  result = solver.check()
  assert(result==z3.sat)

  ##extract the model and make times concrete
  m = solver.model()
  print("soft objective acheived: "+str(m.eval(objective).as_long()))
  #FIXME: this isn't quite what i said would be returned.. pin down api.
  meetings_df['time'] = meetings_df['time'].apply(lambda r: r.make_concrete(m))
  meetings_df['window'] = meetings_df['window'].apply(lambda r: r.make_concrete(m))
  meetings_df['actualattendees']=meetings_df['actualattendees'].apply(lambda r: r.make_concrete(m))
  return result, meetings_df


# if __name__ == '__main__':
