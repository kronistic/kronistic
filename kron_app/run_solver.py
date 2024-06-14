#we're being asked to run the solver! this solverflow gets called any time a
#new schedule needs to be generated -- basically any time the Events table
#changes. 
#this includes: 
  # new/changed meeting from GUI,
  # changed user prefs rom GUI,
  # changed event pushed from gcal,
  # preliminary floating event moved to regular (because all users are now in system, or repair workflow done),
#these are all meant to happen via the task queue, so this will only get called in tasks.py

#Note: currently using default grain of 15min slots.

import os
from copy import deepcopy
from itertools import combinations
import math
from time import process_time, monotonic
from datetime import datetime, timedelta, time, date
from sqlalchemy import update
import psutil
from kron_app.solver.utils import FloatMeeting
from kron_app.solver.solver import solver
# from kron_app.solver.repair import extend_windows
from kron_app import db
from kron_app.models import Event, EventState, FixedEvent, User, Calendar, SolverLog, Change, Email, Attendance
import kron_app.mail as mail
from kron_app.utils import DotDict, to_utc, from_utc, advance_to_midnight, ids
from kron_app.mask_utils import PWlinear, kronduty_masks, make_event_mask
import kron_app.availability as availability

def solver_with_logging(*args, **kwargs):
  caller = kwargs.pop('caller','none')
  now = kwargs.pop('now')
  prov = kwargs.pop('problem_prov')
  floaties = kwargs['floaties']
  num_floaties = len(floaties)
  # now = kwargs['now']
  basetime = kwargs['basetime']
  masks = deepcopy(kwargs['masks'])
  cpustart = process_time()
  wallstart = monotonic()
  p = psutil.Process()
  mem_rss_before = p.memory_info().rss
  mem_available = psutil.virtual_memory().available
  result = solver(*args, **kwargs)
  result_code = result[3]
  pid = os.getpid()
  cputime = round((process_time() - cpustart) * 1000)
  walltime = round((monotonic() - wallstart) * 1000)
  mem_rss_after = p.memory_info().rss
  print(f"++solver return: {result_code}, in {cputime}, on problem size {num_floaties}")
  overlapping = dump_overlapping(floaties) if not result[0] else {}
  db.session.add(SolverLog( data=dict(pid=pid,
                            cputime=cputime,
                            walltime=walltime,
                            mem_rss_before=mem_rss_before,
                            mem_rss_after=mem_rss_after,
                            mem_available=mem_available,
                            caller=caller, 
                            problem_size=num_floaties,
                            result_code=result_code,
                            result=result,
                            floaties=[m.dict() for m in floaties],
                            now=now,
                            basetime=basetime,
                            masks=masks,
                            problem_prov=prov,
                            overlapping=overlapping)))
  db.session.commit()
  return result


def dump_overlapping(floaties):
  try:
    margin = timedelta(minutes=15)
    out = {}
    for e in (e for e in floaties if e.draft_start):
      out[e.id] = {}
      all_attendees = e.attendees + e.optionalattendees
      overlapping_fixed = get_fixed_events(e.draft_start-margin,e.draft_start+e.length+margin,all_attendees)
      out[e.id]['fixed'] = [dict(id=f.id, start_at=f.start_at, end_at=f.end_at, kron_duty=f.kron_duty, calendar_id=f.calendar_id, user_id=f.calendar.user_id) for f in overlapping_fixed]
      overlapping_float = overlapping_draft(e.draft_start-margin,e.draft_start+e.length+margin,all_attendees)
      out[e.id]['float'] = [dict(id=f.id, start_at=f.draft_start, end_at=f.draft_end) for f in overlapping_float if str(f.id) != e.id]
    return out
  except:
    return {}


def event_masks(floaties,now,basetime):
  """
  Get events masks. Returns dotdict keyed by event id string.

  We first grab all the fixed events that could conflict with each floating event,
    which means those that fall within its window and have user in (optional)attendees.
  Floaties that are not added to problem for re-schedule need to be treated as fixed.
   We get those that interact with the problem floaties.
   (Note that this should only be used when we don't unfold teh problem completely.. so currently not..)

  We make from them a piecewise constant function that indicates
    when the event can start and what penalty it incurs in each "bin".
  In addition to kronduty events, need to handle default 9-5 times when no kronduty for a user.
  """  
  floaty_ids = [str(f.id) for f in floaties]
  masks=DotDict({})
  for e in floaties:
    all_attendees = e.attendees + e.optionalattendees
    fixed_events = get_fixed_events(e.window_start,e.window_end,all_attendees)

    #Note: sqla seems to coerce from str to int attendees, but maybe we should do that explicitly?
    draft = overlapping_draft(e.window_start,e.window_end,all_attendees) 
    fixed_drafts = [f for f in draft if str(f.id) not in floaty_ids]

    emasks, optatt_masks = make_event_mask(e,fixed_events,fixed_drafts,now,basetime)
    masks[e.id] = DotDict({'masks': emasks, 'optatt_masks': optatt_masks})

  return masks

# def reasons(e,users,basetime):
#   fixed_events = get_fixed_events(e.window_start,e.window_end,users)

#   kmasks = {}
#   for user_id in users:
#     k, _ = kronduty_masks(fixed_events, basetime, user_id, e.length, people=e.attendees+e.optionalattendees)
#     kmasks[user_id]=k

#   def intersect_masks(us):
#     k=PWlinear(0)
#     for u in us:
#       k.plus(kmasks[u])
#     return k

#   empties=[]
#   for n in range(1,4): #FIXME: go all the way to len(users)?
#     combs=combinations(users,n)
#     empties += [us for us in combs if intersect_masks(us)==PWlinear(math.inf)]
  
#   #keep only minimal empties
#   empties=[e for e in empties if not any([set(e2).issubset(set(e)) for e2 in empties if e!=e2])]

#   return empties 

def get_fixed_events(window_start, window_end, all_attendee_ids):
  #TODO: we filter on a much wider interval to catch all day events, and then filter down to actual intersections... would be nice to avoid that.
  maxoffset = timedelta(hours=14)

  # I split this into two queries, otherwise the index on calendar_id
  # / start_dt / end_dt isn't used -- I don't know why.
  # fixed_events = FixedEvent.query \
  #   .filter((window_start-maxoffset<FixedEvent.end_dt), (window_end+maxoffset>FixedEvent.start_dt)) \
  #   .join(FixedEvent.calendar) \
  #   .filter(Calendar.user_id.in_([int(a) for a in all_attendee_ids])) \
  #   .all()
  calendar_ids = ids(Calendar.query.filter(Calendar.user_id.in_([int(a) for a in all_attendee_ids])).all())
  fixed_events = FixedEvent.query \
    .filter((window_start-maxoffset<FixedEvent.end_dt), (window_end+maxoffset>FixedEvent.start_dt)) \
    .filter(FixedEvent.calendar_id.in_(calendar_ids)) \
    .all()
  fixed_events = [f for f in fixed_events if window_start<f.end_at and window_end>f.start_at]
  # add availability from new ui
  fs = [e.to_fixed_event() for e in availability.get_overlapping(window_start, window_end, all_attendee_ids)]
  fixed_events.extend(fs)
  return fixed_events

def overlapping_draft(start_at, end_at, user_ids):
  return Event.query.filter(Event.state == EventState.SCHEDULED) \
                    .filter(Event.draft_attendees.overlap(user_ids)) \
                    .filter((Event.draft_start<end_at), (Event.draft_end>start_at)) \
                    .all()

#for new spaces, add any event that might want to move into this space...
#TODO: that could be too many, is there a good heuristic for winnowing this?
def overlapping_window(start_at, end_at, user_ids):
  return Event.query.join(Event.attendances, Attendance.email) \
                    .filter((Event.state == EventState.INIT) | (Event.state == EventState.UNSCHEDULED) | (Event.state == EventState.SCHEDULED)) \
                    .filter(Email.user_id.in_(user_ids), Attendance.deleted == False) \
                    .filter((Event.window_start<end_at), (Event.window_end>start_at)) \
                    .all()

def is_conflicted(e,now):
  """check if a (final) event has hard conflicts with its current time"""
  if e.is_scheduled():
    #check if current draft time is allowable:
    masks = event_masks([e],now,now) #CHECK: is basetime=now ok?
    allowed = masks[e.id].masks.hard.abstract_eval(e.draft_start,fn=lambda x,y: not x)
  else:
    #an event without draft times has no hard conflicts...
    allowed=True
  return not allowed

class ProvSet():
  def __init__(self):
    self.elts={}
  
  def __repr__(self):
    return f"{self.elts}"

  def update(self,elts,tag):
    for e in elts:
      if e.id not in self.elts:
        self.elts[e.id] = tag
    return self

def build_problem(now, max_size=100, min_iterations=0, max_iterations=20):
  """
  This fn extracts the problem that needs solving from the db by starting with the "dirty" events (those that are new/changed/deleted since last run). It then builds recursively by finding events that could interact via hard constraints.

  Note: it is possible that we could add soft constraints that would lead to additional interactions between floating events. It is probably not too bad an approximation to leave one fixed though.
  """
  ##get the `dirty` events and build the problem seed from them:
  #TODO: don't need to worry about dirty events before now?
  dirtyFloat = Event.query.filter((Event.state==EventState.INIT) |
                                  (Event.state==EventState.UNSCHEDULED) |
                                  (Event.state==EventState.SCHEDULED)) \
                          .filter_by(dirty=True).all()
  dirtyFixed = FixedEvent.query.filter_by(dirty=True).all()
  changes = Change.query.all()

  print(f"  building problem, {len(dirtyFloat)} dirty floats, {len(dirtyFixed)} dirty fixed, {len(changes)} changes..")


  # TODO: `candidate_ids` is used -- remove?

  # The subset of the problem set that will be used as repair
  # candidates. in principle the candidate set should be such that if
  # all those events are removed, the existing schedule is sat. then
  # repair will always succeed because the candidate set are made
  # optional.
  candidate_ids = set(str(d.id) for d in dirtyFloat)

  spaces=set()
  conflicts=set()
  prov=ProvSet()
  for e in dirtyFloat:
    tag = e.state_name.lower() + 'Float'
    if e.is_final():
      tag += "_final"
    if e.is_draft():
      tag += "_draft"
    prov.update([e],tag)

  for c in changes:
    if c.conflict:
      events = overlapping_draft(c.start_at, c.end_at, c.users)
      candidate_ids.update(str(e.id) for e in events)
      conflicts.update(events)
      prov.update(events,"change_conflict")
    else:
      events = overlapping_window(c.start_at, c.end_at, c.users)
      spaces.update(events)
      prov.update(events,"change_space")

  for d in dirtyFixed:
    # dirty fixed events are potential conflicts
    events = overlapping_draft(d.start_at, d.end_at, [d.calendar.user_id])
    candidate_ids.update(str(e.id) for e in events)
    conflicts.update(events)
    prov.update(events,"dirtyFixed_conflict")


  #Events that are "final" should only be added to problem if they have a true conflict. events that are "past" (start before now) should never be added to problem.
  problemset = set(dirtyFloat) | conflicts | spaces
  problemset = {e for e in problemset if not e.in_progress(now)} # db queries already excluded floaties that have finished
  nosolve = {e for e in problemset if e.is_final() and not is_conflicted(e,now)}
  problemset = problemset - nosolve

  print(f"  building problem, after dirty and changes {len(problemset)} floats..")
  print(f"  skipping {len(nosolve)} non-conflicted final floats..")


  # TODO: Concurrency
  # This obviously isn't safe to run concurrently (non-atomic
  # read-modify-write of flags / changes.) That can probably be fixed
  # with SELECT FOR UPDATE (ordered by e.g. id to guard against
  # deadlocks). More important is the question of whether there are
  # more subtle concurrency issues here. Maybe we need to be sure we
  # always see the dirty fixed event / change relating to a fixed
  # event move in the same solver run. In which case the fact that (a)
  # we fetch those with two queries and (b) a write can happen in
  # between is a potential bug. (This is just an example, it might not
  # actually be a problem, I've not thought it through.) There
  # certainly are issues with the wider `run_solver` -- an obvious one
  # is we don't handle a meeting disappearing by the time we come to
  # update its draft start / end times -- but there are others. This
  # all needs careful thought.
  db.session.execute(update(Event).values(dirty=False))
  db.session.execute(update(FixedEvent).values(dirty=False).where(FixedEvent.dirty==True))
  for c in changes: # Only delete accounted-for changes. (Because the availability UI runs concurrently, for example.)
    db.session.delete(c)
  db.session.commit()

  problemset, prov = expand_problem(now, problemset, prov,max_size, min_iterations,max_iterations)
   
  print(f" buildproblem provenances {prov}")
    
  return problemset, nosolve, candidate_ids, prov

def expand_problem(now, problemset, prov, max_size=100, min_iterations=0,max_iterations=20):
  ##now we iteratively build out the problem:
  ## for now we include those events that have overlapping attendees and overlapping windows
  oldsize=0
  for iteration in range(max_iterations):
    for d in problemset.copy():
      if ((len(problemset) >= max_size) and (iteration >= min_iterations)): 
        #return if problem exceeds bounds:
        return problemset, prov

      #TODO: keep track of new events from last iteration, only get neighbors of these.
      all_attendees = d.attendees + d.optionalattendees
      neighbors = overlapping_window(d.window_start, d.window_end, all_attendees)
      neighbors=[n for n in neighbors if not (n.is_final() or n.in_progress(now))]
      newneighbors = set(neighbors)-problemset
      if (len(newneighbors)+len(problemset)>max_size) and (iteration >= min_iterations):
        newneighbors=list(newneighbors)[:max_size-len(problemset)]
        #TODO: could simplify by putting the return on len(problemset)>=max_size here instead of above?
      problemset.update(newneighbors)
      prov.update(newneighbors,f"expand-{iteration}")

    if len(problemset) == oldsize: 
      #return if problemset has converged:
      return problemset, prov
    oldsize=len(problemset)
    print(f"  building problem, expanded problemset size {len(problemset)}")

  return problemset, prov

#define an exception subclass for solver errors:
class SolverError(Exception):
  pass

def run_solver(now=None, config={'timeout': 60000}):
  if now is None:
    now=datetime.utcnow()

  # Build a list of event ids that need to be sync'd and emails to be
  # sent, deferring execution to the queue. This simplifies testing.
  tosync = []
  emails = []

  def queue_meeting_unscheduled_email(event, prev_state):
    email = mail.meeting_unscheduled(event)
    hold_off_secs = 480 if prev_state == EventState.SCHEDULED else 0
    emails.append((email, event.id, EventState.UNSCHEDULED, hold_off_secs))

  def queue_meeting_rescheduled_email(event):
    for id in event.draft_attendees:
      user = User.query.get(id)
      email = mail.meeting_rescheduled(user, event)
      emails.append((email, event.id, None, 0))

  events, nosolve, _, prov = build_problem(now,max_size=50,min_iterations=0)

  for e in (e for e in nosolve if e.is_scheduled()):
    # Propagate changes to draft_* cols and to calendars...
    #
    # Reflect changes (both additions and removals) in required
    # attendees. It is safe to add new attendees because we know from
    # `is_conflicted` that hard constraints are met.
    #
    # We don't know whether new optional attendees are safe to add, so
    # we don't. (However, like all "unavailable" attendees, they will
    # still be included on the calendar entry as an optional guest.)
    opt_made_it = set(e.draft_attendees) & set(e.optionalattendees)
    e.draft_attendees = list(set(e.attendees) | opt_made_it)
    # No hard conflicts also means this is safe.
    e.draft_end = e.draft_start + e.length
    tosync.append(e.id)
  db.session.commit()

  if len(events) == 0:
    return tosync, emails

  #we use hour of earliest meeting window as basetime (internal 0). 
  #  this can be anything on grain grid, but it's convenient to tie it to the problem.
  basetime = min([e.window_start for e in events]).replace(second=0, microsecond=0, minute=0)

  floaties = [FloatMeeting.from_orm(m) for m in events]

  masks = event_masks(floaties,now,basetime)

  #check for empty hard masks, for such events remove from problem if they are optional.
  impossible_events = [id for id,m in masks.items() if m.masks.hard==PWlinear(math.inf)]
  floaties = [f for f in floaties if f.id not in impossible_events]
  
  print(f"  {len(impossible_events)} impossible, remaining problem size {len(floaties)}.")

  result, schedule, unschedueled_ids, result_code = solver_with_logging(floaties=floaties,now=now,basetime=basetime,masks=masks,caller='main',config=config,problem_prov=prov)

  #add the events we skipped into unscheduled ids
  unschedueled_ids += impossible_events

  if not result:
    #no result.. it's not clear how this is possible.
    raise SolverError(f"Solver failed with result code {result_code}")
    # #since dirty flags have already been cleared we pessimistically set all candidates to optional, 
    # # this will keep from baking in unsat constraints but it won't necessarily avoid hitting this situation again...
    # #FIXME: i think with all events always "optional" we don't need this?
    # for mid in candidate_ids:
    #   print(f" triage candidate event {mid} made optional.")
    #   #couldn't schedule this event. make permanently optional and notify owner:
    #   event = Event.query.get(int(mid))
    #   #event as permanently optional.
    #   # event.priority=10
    #   event.draft_start = None # Un-schedule -- this event may previously have been scheduled.
    #   event.draft_end = None
    #   event.draft_attendees = []
    #   prev_state = event.state
    #   event.state = EventState.UNSCHEDULED
    #   # db.session.add(event)
    #   db.session.commit()
    #   tosync.append(event.id)
    #   queue_meeting_unscheduled_email(event, prev_state)
    # #raise SolverError(f"{result_code} on repair")
    # return tosync, emails
  
  #unpack the schedule and add draft times to floating events in database
  #  we'll get back a list of DraftMeeting pydantic objects, use them to update Event db
  for m in schedule:
    event = Event.query.get(int(m.id))
    rescheduled = event.draft_start != m.start
    event.draft_start = m.start
    event.draft_end = m.end
    event.draft_attendees = [int(a) for a in m.actualattendees]
    event.state = EventState.SCHEDULED
    
    # call the helper routine to propogate to/sync floating event drafts to google calendars
    tosync.append(event.id)
    if event.is_final() and rescheduled:
      queue_meeting_rescheduled_email(event) # call after updating attendees


  for unschedueled_id in unschedueled_ids:
    event = Event.query.get(int(unschedueled_id))
    if not event.is_unscheduled():
      #these are the events that are transitioning into UNSCHEDULED. 
      #send a repair email:
      print(f"unscheduling event {event.id} and sending email..")
      queue_meeting_unscheduled_email(event, event.state)
      event.draft_start = None
      event.draft_end = None
      event.draft_attendees = []
      # event.priority=10 #TODO what priority should these be? high so that get rescheduled if possible..
      event.state = EventState.UNSCHEDULED
      tosync.append(event.id)
  
  db.session.commit()
  # all done, yay!
  return tosync, emails


if __name__ == '__main__':
  run_solver()
