
from datetime import datetime, timedelta
from itertools import combinations
import math
from kron_app.mask_utils import Edge, PWlinear, Topo, trim_window_start, user_masks
from kron_app.utils import ids, dictunion
from kron_app.models import Calendar, FixedEvent
from kron_app.solver.utils import FloatMeeting
from kron_app.run_solver import ProvSet, event_masks, expand_problem, get_fixed_events, solver_with_logging

"""
Some notes on kinds of reasons:

- special case when an event is impossible in isolation (without considering other float events)
  - sub-special case when a single attendee has no availability.
  - differentiate if this attendee has no kronduty or no hard availability.

- "event unscheduled because of attendees abc": find minimal set of attendees st if they were optional meeting could be scheduled. report set and resulting draft time?
  - offer to make those attendeed optional.
- "event unscheduled because of other events E": find minimal set of other meetings (by same owner? with certain attendees?) st if they were optional this one could be scheduled.
  - offer to delete or unschedule those events?
- "event unscheduled because window is too short": find window extension that would make meeting possible (if any).
  - offer to extend window.
- "event unscheduled because meeting too long": find shorter length st meeting could be scheduled. (note this is hard with current solver setup because length is baked into masks.)

"""

def impossible_because_users(event):
  """determine if event is impossible, given only fixed events and kronduty.
  if so, return minimal sets of users that have no overlapping availability (resulting in the event being impossible).
  when a set is singleton (ie a single user has no availability) also determine if this is true only due to kronduty."""

  users=[str(eid) for eid in event.attendees]
  now=datetime.utcnow()
  basetime=datetime.utcnow() #CHECK: this is ok?
  start=event.window_start
  end=event.window_end
  fixed_events = get_fixed_events(start,end,users)

  #NOTE: assume no fixed drafts for purposes of finding hard conflicts
  umasks = user_masks(fixed_events, [], users,event,basetime)

  #build hard mask to check if this event is impossible:
  window_start = trim_window_start(event, now)
  hardmask = PWlinear(math.inf, Edge(window_start,Topo.RIGHT), 0, Edge(event.window_end-event.length,Topo.LEFT), math.inf)
  #TODO: case where window_start>e.window_end-e.length ??
  for m in umasks.values():
    hardmask.plus(m.kronduty).plus(m.fixed)

  if hardmask==PWlinear(math.inf):
    #event is impossible, figure out why...
    kmasks = {k:v.kronduty for k,v in umasks.items()}
    fmasks = {k:v.fixed for k,v in umasks.items()}
    empties = minimal_empty_intersection(users, kmasks, fmasks)
    #when a set is singleton (ie a single user has no availability) also determine if this is true only due to kronduty:
    unavailable_users=[u[0] for u in empties if len(u)==1]
    unavailable_users=[(u,PWlinear(math.inf, Edge(window_start,Topo.RIGHT), 0, Edge(event.window_end-event.length,Topo.LEFT), math.inf).plus(kmasks[u])==PWlinear(math.inf)) for u in unavailable_users]
    return False, empties, unavailable_users

  else:
    return True, [], [] #event is actually possible locally...



def solve_for(event,modifier):
  """this is the helper method used to run the solver for 'counterfactual' schedule exploration. 
  build out a problem from event, modifying the problem set by calling `modifier`, 
  which gets and returns the target floaty and the rest of teh floaties.
  TODO: add params to set expand problem size and timeout -- want this to be pretty fast.
  """
  now=datetime.utcnow()
  #build problem from event
  prov=ProvSet()
  prov.update([event], 'reasons')
  events, prov = expand_problem(now,{event},prov)
  basetime = min([e.window_start for e in events]).replace(second=0, microsecond=0, minute=0)
  floaties = [FloatMeeting.from_orm(m) for m in events]
  
  #modifier makes whatever changes we want to consider a looser problem..
  target=next(f for f in floaties if f.id==str(event.id))
  others=[f for f in floaties if f.id!=str(event.id)]
  print(f"target before modifier {target}")
  target, others=modifier(target, others)
  print(f"target after modifier {target}")
  new_floaties=others+[target]

  masks = event_masks(new_floaties,now,basetime)
  result, schedule, unschedueled_ids, result_code = solver_with_logging(floaties=new_floaties,now=now,basetime=basetime,masks=masks,caller='counterfactual',problem_prov=prov)

  return result,schedule,unschedueled_ids


def unscheduled_because_users(event):
  """find minimal set of attendees st if they were optional meeting could be scheduled. 
  return this set and resulting draft time.
  if event is impossible (even with all users optional), return empty set and None."""

  def modifier(target,others):
    #modify target float st all attendees of event are optional, but higher priority for 'required' attendees
    # for a in target.attendances:
      # if a.optional:
      #   a.priority=0 #TODO: only shift down but not to 0?
      # else:
      #   a.priority=100
      #   a.optional=True
    target.optionalattendeepriorities=dictunion({a:100 for a in target.attendees},{a:0 for a in target.optionalattendees})
    target.optionalattendees= target.attendees+target.optionalattendees
    target.attendees=[]
    return target, others

  original_attendees = [str(eid) for eid in event.attendees]
  result,schedule,unschedueled_ids = solve_for(event,modifier)

  #confirm event was scheduled and see which attendees were included
  if schedule and  str(event.id) not in unschedueled_ids:
    target=next(f for f in schedule if f.id==str(event.id))
    leftovers =  set(original_attendees) - set(target.actualattendees)
    return leftovers, target.start
  else:
    return [], None



def unscheduled_because_events(event):
  """find minimal set of other meetings (by same owner? with certain attendees?) st if they were optional this one could be scheduled.
  do this by setting this meeting to required and others 'nearby' to optional. """

  def modifier(target,others):
    #modify other floats to be optional
    target.is_optional=False
    target.priority=None
    for other in others:
      other.is_optional=True
      other.priority = 20
    return target, others

  result,schedule,unschedueled_ids = solve_for(event,modifier)

  if str(event.id) not in unschedueled_ids:
    target=next(f for f in schedule if f.id==str(event.id))
    bumped=unschedueled_ids #TODO: should this be only those that weren't previously unscheduled?
    return bumped, target.start
  else:
    return [], None

def unscheduled_because_window(event):
  """find window extension that would make meeting possible (if any).
  note: this is currently done automatically in repair, but perhaps we want to offer instead as a fixit option?"""

  def modifier(target,others):
    #modify target float to have longer window
    extra_time = (target.window_end-target.window_start)
    extra_time = max(timedelta(days=7), extra_time)
    target.window_end = target.window_end + extra_time
    return target, others

  result,schedule,unschedueled_ids = solve_for(event,modifier)

  #check if event was scheduled, if so return end
  if str(event.id) not in unschedueled_ids:
    target=next(f for f in schedule if f.id==str(event.id))
    return target.end
  else:
    return None
  





# def reasons(e,basetime):
#   users=[str(eid) for eid in e.attendees]
#   fixed_events = get_fixed_events(e.window_start,e.window_end,users)

#   #NOTE: assume no fixed drafts for purposes of finding hard conflicts
#   umasks = user_masks(fixed_events, [], users,e,basetime)
#   kmasks = {k:v.kronduty for k,v in umasks.items()}
#   fmasks = {k:v.fixed for k,v in umasks.items()}
#   empties = minimal_empty_intersection(users, kmasks, fmasks)

#   return empties 

def intersect_masks(us,*masks):
  k=PWlinear(0)
  for u in us:
    for m in masks:
      k.plus(m[u])
  return k

def minimal_empty_intersection(users, *masks):
  empties=[]
  max_combo = min(6,len(users)+1) #FIXME: go all the way to len(users)?
  for n in range(1,max_combo): 
    combs=combinations(users,n)
    empties += [us for us in combs if intersect_masks(us,*masks)==PWlinear(math.inf)]

  #keep only minimal empties
  empties=[e for e in empties if not any([set(e2).issubset(set(e)) for e2 in empties if e!=e2])]
  return empties
