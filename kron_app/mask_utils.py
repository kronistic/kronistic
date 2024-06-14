from copy import deepcopy
import math
from enum import Enum, auto
from datetime import datetime, timedelta
from kron_app.utils import DotDict
from kron_app.users import find_user_by_email
from kron_app.models import User
from kron_app.groups import unpack_groups

SOONER_WEIGHT = 100.0
IFNEEDED_WEIGHT = 500.0
UNFREEZE_COST = IFNEEDED_WEIGHT*10 #TODO: this weight should perhaps depend on number of attendees?


class Topo(Enum):
  LEFT = auto() # ..[v)..
  RIGHT= auto() # ..(v]..
  # ..[v].. will expand to interval with no distance and ..(v]..[v)..
  # ..(v).. shouldn't be used because we make total functions.

class Edge():
  #A domain edge
  def __init__(self, x, side: Topo = Topo.LEFT):
    #val is the real value of this domain edge
    self.val=x
    #side indicates the edge topology: are left and/or right intervals closed?
    self.side=side

  def __eq__(self, other):
    return isinstance(other,Edge) and self.val==other.val and self.side==other.side

  def __str__(self):
    if self.side==Topo.RIGHT:
      return f"({self.val}]"
    elif self.side==Topo.LEFT:
      return f"[{self.val})"
    else:
      return f"[{self.val}]"

  def __repr__(self):
    return f"Edge({repr(self.val)},{self.side})"

  def __lt__(self,other):
    return self.val<other.val

class PWfn():
  def __init__(self,*args):
    #args should be (val, edge, val, edge,...,val)
    self.data=list(args)

  def __eq__(self,other):
    return isinstance(other,PWfn) and self.data == other.data

  def __str__(self):
    return f"{self.data}"

  def __repr__(self):
    return f"PWfn(*{repr(self.data)})"


  def zip(self,other):
    """
    zip together the functions by intersecting domains, values will be pairs (self, other) vals.
    when domain edges coincide we have to be a bit careful:
      eg ..u(x]v.. zipped with ..r[x)s.. becomes ..(u,r)(x](v,r)[x)(v,s)..
    TODO: there must be a nicer way to do this?
    """
    currs=self.data[0]
    curro=other.data[0]
    new_data=[(currs,curro)]
    idxs=1
    idxo=1

    while idxs<len(self.data) or idxo<len(other.data):

      #emmit edge from whichever has next boundary:
      # 
      self_next = idxs<len(self.data) and (not idxo<len(other.data) or self.data[idxs]<other.data[idxo])
      other_next = idxo<len(other.data) and (not idxs<len(self.data) or other.data[idxo]<self.data[idxs])
      if self_next:
        new_data.append(self.data[idxs])
        currs=self.data[idxs+1]
        idxs += 2 
      elif other_next:
        new_data.append(other.data[idxo])
        curro=other.data[idxo+1]
        idxo += 2
      else: # next edges are equal val
        self_edge=self.data[idxs]
        other_edge=other.data[idxo]
        assert self_edge.val==other_edge.val #TODO: remove assert when i'm sure this works
        #if they agree on topology:
        if self_edge.side == other_edge.side:
          new_data.append(self_edge)
        #otherwise they disagree and we have to reconcile the by emmiting an extra interval
        else:
          new_data.append(Edge(self_edge.val,side=Topo.RIGHT))
          self_val = currs if self_edge.side==Topo.LEFT else self.data[idxs+1]
          other_val = curro if other_edge.side==Topo.LEFT else other.data[idxo+1]
          new_data.append( (self_val,other_val) )
          new_data.append(Edge(self_edge.val,side=Topo.LEFT))
          #if one has a detatched point, u,(x],v,[x),w but the other doesn't, r,[x),s,[z),t..
          # then we need to emmit (x],(v,r),[x),(w,s)... to do that must jump the one that's detatched
          if idxs+2<len(self.data) and self_edge.val==self.data[idxs+2].val:
            idxs += 2
          if idxo+2<len(other.data) and other_edge.val==other.data[idxo+2].val:
            idxo += 2
        #now advance both to next edge:
        currs=self.data[idxs+1]
        idxs += 2
        curro=other.data[idxo+1]
        idxo += 2
      # emmit pair of values for next interval:
      new_data.append( (currs,curro) )
    self.data=new_data
    return self

  def apply_vals(self, fn):
    """apply fn to the value in each domain"""
    for i in range(0,len(self.data),2):
      self.data[i]=fn(self.data[i])
    return self

  def apply_edges(self, fn):
    """apply fn to the Edge values (keep side topology)
    FIXME: catch cases where a domain collapses to a point?"""
    for i in range(1,len(self.data),2):
      x=fn(self.data[i].val)
      self.data[i] = Edge(x,self.data[i].side)
    # self.simplify() #to remove any now trivial intervals
    return self

  def apply_domains(self,fn):
    data = [Edge(-math.inf,Topo.RIGHT)]+self.data+[Edge(math.inf,Topo.LEFT)]
    for i in range(0,len(data)-2,2):
      data[i:i+3]=fn(*data[i:i+3]) #use fn to update edge_i,val,edge_i+1
    self.data = data[1:-1]
    # if len(self.data)==1:
    #   self.data[0]=fn(Edge(-math.inf,Topo.RIGHT),self.data[0],Edge(math.inf,Topo.LEFT))[1]
    # else:
    #   self.data[0:1]=fn(Edge(-math.inf,Topo.RIGHT),self.data[0],self.data[1])[1:2]
    #   for i in range(1,len(self.data)-2,2):
    #     self.data[i:i+3]=fn(*self.data[i:i+3]) #use fn to update edge_i,val,edge_i+1
    #   self.data[-2:-1]=fn(self.data[-2],self.data[-1],Edge(math.inf,Topo.LEFT))[0:1]
    self.simplify() #to remove any now trivial intervals
    return self

  def simplify(self, eq=lambda a,b: a == b):
    """merge together domains with equal values"""
    curr_val=self.data[0]
    new_data=[curr_val]
    for i in range(1,len(self.data),2):
      if not eq(self.data[i+1], curr_val):
        curr_val=self.data[i+1]
        new_data.append(self.data[i])
        new_data.append(curr_val)
    self.data=new_data
    return self

  def combine(self,other,fn):
    """combine self and other. fn takes two args."""
    self.zip(other).apply_vals(lambda p: fn(*p)).simplify()
    return self

  def apply(self,fn):
    """helper to apply and siplify"""
    self.apply_vals(fn).simplify()
    return self

  def abstract_eval(self, x, If = lambda x,y,z: y if x else z, fn = lambda v: v):
    """
    returns the pw function evaluated at x but uses function If for conditionals in 
    order to ennable overloading (eg with z3 If). when fn is provided returns f(pw(x)), so
    that non-standard eval will happen in place.

    assumes that if x is a non-standard value it implements comparison (with the Edge values).

    there are various ways to make the search tree. here we basically do binary search.
    """

    #add the -inf and inf edge:
    data = [Edge(-math.inf,True)]+self.data+[Edge(math.inf,True)]

    def helper(lower_idx,upper_idx):
      if upper_idx - lower_idx ==2: #narrowed to a single interval
        return fn(data[lower_idx+1])
      elif upper_idx == lower_idx: #x is an edge
        val = data[lower_idx+1] if data[lower_idx].side==Topo.RIGHT else data[lower_idx-1]
        return fn(val)
      else:
        test_idx= lower_idx + 2*int(((upper_idx - lower_idx)/2)//2)  #the first /2 is because values alternate with bin marks
        test_x=data[test_idx].val

        left_case = helper(lower_idx,test_idx)
        right_case = helper(test_idx,upper_idx)
        equal_case = helper(test_idx,test_idx)
        
        return If(x<test_x,left_case,If(x>test_x,right_case,equal_case))

    return helper(0,len(data)-1)

def eq_line(a,b):
  #helper. equality for two lines a,b -- if constants are both inf they are equal
  if a[1]==math.inf and b[1]==math.inf:
    return True
  else:
    return a == b

class PWlinear(PWfn):
  """
  this is a piecewise linear function. 
  each domain represents linear function y=m*x+b; the values are (m,b)
  this class just implements some helpers for linears..
  since z3 doesn't deal well with inf, evaluation actually passes 
  a pair of is_inf and y to the continuation fn.
  TODO: keep around max and min bounds, to help cost iterpretation in solver.
  """
  def __init__(self,*args):
    #add defaults m=0 for vals
    data = list(args)
    for i in range(0,len(data),2):
      data[i] = (0,data[i]) if not isinstance(data[i],tuple) else (0,data[i][0]) if len(data[i])<2 else data[i]
    super().__init__(*data)

  def __repr__(self):
    return f"PWlinear(*{repr(self.data)})"

  def simplify(self):
    """merge together domains with equal values and domains that both have inf constant term"""
    # self.apply_vals(lambda p: p if p[1]!=math.inf else (0,math.inf))
    super().simplify(eq_line)
    return self

  def plus(self,other):
    self.combine(other,lambda a,b: (a[0]+b[0],a[1]+b[1]))
    return self

  def scalar_mult(self,s):
    self.apply(lambda x: (s*x[0],s*x[1]))
    return self

  def abstract_eval(self, x, If = lambda x,y,z: y if x else z, fn = lambda y: y):
    """assume abstract vals x implement float*x """
    def linearfn(p):
      if p[1]==math.inf:
        return fn(True,math.inf)
      elif p[0]==0:
        return fn(False,p[1])
      else:
        return fn(False, p[0]*x + p[1])
    return super().abstract_eval(x,If,linearfn)

# def mk_relu(x0,x1,y0=0,y1=1,basetime=datetime(2022,6,22)):
#   #make a relu, with slope in 1/sec units
#   # intercept b is the y value when x=basetime
#   # so later we will need to convert datetime as offsets from this basetime
#   # before computing value of linear
#   #Note: awkwardly we don't represent edges as deltas from basetime.
#   #FIXME: clean this up so there aren't conversions to seconds from basetime in multiple places.
#   if x0==x1:
#     #degenerate case become step fn, edge is closed left
#     return PWlinear(y0,Edge(x0),y1)
#   m=(y1-y0)/(x1-x0).total_seconds()
#   # y1=m*x1+b.. b=y1-m*x1
#   b=y1 - m*(x1-basetime).total_seconds()
#   return PWlinear(y0,Edge(x0),(m,b),Edge(x1),y1)

def mk_path(*args,basetime=datetime(2022,6,22)):
  """
  from a list of pairs [(x0,y0)..(xn,yn)] make a PWlinear that:
    is constant at y0 up to x0,
    linearly interpolates (xi,yi) to (xi+1,yi+1),
    is constant yn after xn
  slopes are represented in 1/sec units
  intercepts b are the y value when x=basetime
  (so later we will need to convert datetime as offsets from this basetime before eval the PWlinear.)
  Note: awkwardly we don't represent edges as deltas from basetime.
  FIXME: clean this up so there aren't conversions to seconds from basetime in multiple places.
  """
  path=[args[0][1]]
  for p0,p1 in zip(args[:-1],args[1:]):
    if p0[0]==p1[0]:
      #degenerate case becomes step fn, with the point being the LEFT y value
      #edge closed right to indicate disconnected point, but will be removed in simplify
      m=0
      b=p0[1]
      path.append(Edge(p0[0],Topo.RIGHT))
      path.append((m,b))
      print(f"**degenerate path case.")
    else:
      m=(p1[1]-p0[1])/(p1[0]-p0[0]).total_seconds()
      # y1=m*x1+b.. b=y1-m*x1
      b=p1[1] - m*(p1[0]-basetime).total_seconds()
      path.append(Edge(p0[0]))
      path.append((m,b))
  path.append(Edge(args[-1][0],Topo.RIGHT)) #final edge is closed toward the constant fn
  path.append(args[-1][1])

  return PWlinear(*path).simplify()


def make_event_mask(e, fixies, fixed_draft, now, basetime=datetime(2022,6,22)):
  """
  make a mask indicating available times and costs.
  e is a FloatMeeting (or Event? similar interfaces).
  fixies is a list of FixedMeeting that affect this event.
  fixed_draft is a list of Events that should be treated as fixed conflicts.
  initial mask comes from window, adjusted for freeze horizon.
  for each attendee we make a kronduty mask by unioning their available times.
  we then combine kronduty times across users and all the fixed events by sum (intersection).
  optional attendees are treated a bit differently: for now we make a mask for each, but don't
    intersect with the main mask. this should be done if attendee is in event... 
  note: should be mask of *start* times, so need to adjust end of intervals based on event length.
  """

  window_start = trim_window_start(e, now)

  if window_start>e.window_end-e.length:
    print(f" skipping mask for event {e.id} because window is null. now {now}, latest start time {e.window_end-e.length}.")
    return DotDict({'window':PWlinear(math.inf),'fixed':PWlinear(0),'ifneeded':PWlinear(0), 'kronduty':PWlinear(0), 'sooner':PWlinear(0), 'hard':PWlinear(math.inf)}), {}
    
  windowmask = PWlinear(math.inf, Edge(window_start,Topo.RIGHT), 0, Edge(e.window_end-e.length,Topo.LEFT), math.inf)
  # #add a cost representing the freeze horizon "buffer":
  # if now+e.freeze_horizon>window_start:
  #   buffermask=PWlinear(UNFREEZE_COST, Edge(now+e.freeze_horizon,Topo.RIGHT), 0)
  #   windowmask.plus(buffermask)

  #masks for required users
  umasks = user_masks(fixies,fixed_draft,e.attendees,e,basetime)
  #keep components, but smoosh across users
  masks = DotDict({'window':windowmask,'fixed':PWlinear(0),'ifneeded':PWlinear(0), 'kronduty':PWlinear(0)})
  for k,v in umasks.items():
    masks.fixed.plus(v.fixed)
    masks.ifneeded.plus(v.ifneeded)
    masks.kronduty.plus(v.kronduty)

  #masks for optional users.
  umasks = user_masks(fixies,fixed_draft,e.optionalattendees,e,basetime)
  optatt_masks = DotDict({})
  #smoosh the components together but keep separated by user
  #TODO: keep in components?
  for k,v in umasks.items():
    optatt_masks[k] = deepcopy(windowmask).plus(v.fixed).plus(v.ifneeded).plus(v.kronduty)

  #add soft constraints based on absolute time, such as "sooner mtgs", to mask.
  #Note: this sooner_mask implies that its more urgent to shcedule a meeting with shorter window soon than one with longer window... is that reasonable?
  # if e.window_end-e.length == window_start:
  #   sooner_mask = PWlinear(0,Edge(0,Topo.Left),SOONER_WEIGHT)
  # else:
  # sooner_mask = mk_path((window_start,0),(e.window_end-e.length,SOONER_WEIGHT),basetime=basetime)
  
  run = (e.window_end-e.length-window_start).total_seconds()
  if run != 0:
    slope=SOONER_WEIGHT/run
    # y1=m*x1+b.. b=y1-m*x1
    b= -slope*(window_start-basetime).total_seconds()
    # sooner_mask = PWlinear(0,Edge(m['window'].start),(slope,b),Edge(m['window'].start+m['window'].length-m['time'].length),1.0)
    sooner_mask = PWlinear( (slope,b) )
  else:
    sooner_mask = PWlinear(0)

  # mask.plus(sooner_mask).simplify()
  masks.sooner=sooner_mask

  #check masks to see if we already know that a meeting is unsat..
  hard_masks = deepcopy(masks.window)
  hard_masks.plus(masks.fixed).plus(masks.kronduty).simplify()
  masks.hard = hard_masks
  if hard_masks == PWlinear(math.inf) and not e.is_optional:
    # TODO: unreachable, since events are always optional -- remove?
    print(f"***hard masks are unsat for required event {e.id}!")
    if masks.fixed == PWlinear(math.inf):
      print("   fixed events leave no possible time.")
    if masks.kronduty == PWlinear(math.inf):
      print("   kronduty intersections leave no possible time.")

  #TODO: once we add "springs" we'll need to keep track of those for fixed_draft in a similar way.
  return masks, optatt_masks

def trim_window_start(e, now):
  #trim mask so event isn't scheduled before now+freeze_horizon,
  #or before draft_start for final meeting. (if final and no draft start after now..)
  if e.final and e.draft_start:
    window_start = max(min(e.draft_start, now+e.freeze_horizon), e.window_start, now)
  # elif e.final: #final but no draft start time
  #   window_start = max(e.window_start, now+e.freeze_horizon)
  else:
    window_start = max(e.window_start, now+e.freeze_horizon)
    
  return window_start

def user_masks(fixies, fixed_draft, users, event, basetime):
  """
  this returns a dict keyed by user id (str) with values that are the core mask components (fixed, ifneeded, kronduty) for that user for the event.
  used for setting up solver masks and reading repair tea leaves.
  """
  user_masks={}
  for user in users:
    m=DotDict({})
    m.fixed = fixedevent_mask(fixies,fixed_draft,user,event)   
    kmask, imask = kronduty_masks(fixies, basetime, user, event.length,people=event.attendees+event.optionalattendees)
    m.ifneeded = imask
    m.kronduty = kmask
    user_masks[str(user)]=m
  return user_masks

def fixedevent_mask(fixies, fixed_draft, user, event):
  """
  find the availabaility of the user for this event, given fixed events (and fixed drafts).
  """
  fmask = PWlinear(0)
  for f in fixies:
    if int(user)==f.calendar.user_id and not f.kron_duty:
      fmask.plus(PWlinear(0,Edge(f.start_at-event.length,Topo.LEFT),math.inf,Edge(f.end_at,Topo.RIGHT),0))
  for f in fixed_draft:
    if int(user) in f.draft_attendees:
      fmask.plus(PWlinear(0,Edge(f.draft_start-event.length,Topo.LEFT),math.inf,Edge(f.draft_end,Topo.RIGHT),0))
  return fmask

def kronduty_masks(fixies, basetime, user, event_length,people=[]):
  """
  we want to find the availability of user for the people listed in people, based on the kronduty events in fixies.
  user should be a user id.
  people should be a list of user ids.
  """
  groups = User.query.get(user).groups #TODO i wish there was a way to do this without touching the db...
  # print(f"user {user}, people {people}, groups {groups}")
  #people shouldn't include self:
  people = [p for p in people if int(p)!=int(user)]
  kmask = PWlinear(0)
  imask = PWlinear(0)
  for f in fixies:
    if int(user) == f.calendar.user_id and f.kron_duty:
      cost = f.costs.pop('everyone',math.inf)
      #we add segments to masks (indicating available time for this meeting) if cost is finite
      if math.isfinite(cost):
        # union availability into kronduty times for user:
        if f.kind == 'availability':
          kmask.plus(PWlinear(0,Edge(f.start_at,Topo.RIGHT),1,Edge(f.end_at,Topo.LEFT),0))

        """
        add in ifneeded penalities. 
        we go ahead and do this even when cost==0, though it will have no effect in that case.

        the semantics should be such that the penalty is the same if i make one long or two short adjacent times (all with same priority).
        this means we can't use proportion of f covered as the measure.
        we could use proportion of event covered, but this means really big events "pay less" for using the same ifneeded time.
        so it seems like the penalty should be based on actual ifneeded time used. that is, "if needed" corresponds to eg cost units of cost-per-hour-used.
        the downside of this is that there is no upper bound to the cost incurrable by ifneeded times, so we'll have to be careful in balancing cost/preferences. 
        the overlap fn is: 
        amount of event past f.start_at - amount of event past f.end_at
        and the amount past z is: 0 until f.start_at-event.length, event.length after f.start_at,
        and linear interp between.
        """
        #cost is cost per hour used, times weight:
        max_cost=IFNEEDED_WEIGHT * cost * (event_length/timedelta(hours=1)) 
        past_fstart=mk_path((f.start_at-event_length,0),(f.start_at,max_cost),basetime=basetime)
        past_fend=mk_path((f.end_at-event_length,0),(f.end_at,-max_cost),basetime=basetime)
        ifneeded=past_fstart.plus(past_fend)
        imask.plus(ifneeded)
        # print(f"imask {imask}")
  #kmask>0 is now allowable times, need to account for meeting length.
  # to do so, set the edge after an interval with val>0 back by meeting length, 
  # if it passes the edge before it discard the interval (meeting won't fit)
  def kronduty_fit_helper(e1,v,e2):
    if v[1]>0:
      if e2.val-event_length>=e1.val:
        e2=Edge(e2.val-event_length,e2.side)
        return e1,v,e2
      else: 
        return e1,(0,0),e1
    else:
      return e1, v, e2
  kmask.apply_domains(kronduty_fit_helper)
  #invert so avialable becomes 0, unavailable inf, to match other masks.
  kmask.apply(lambda p: (0,0 if p[1]>0 else math.inf))
  return kmask,imask

# def discretize(e1,v,e2):
#   e1=Edge(inf_floor(e1.val),e1.side)
#   e2=Edge(inf_floor(e2.val),e2.side)
#   m,b = v
#   if b == math.inf:
#     return e1,(m,b),e2
#   x1=e1.val
#   x2=e2.val 
#   y1 = m*x1 + b
#   y2 = m*x2 + b     
#   if x1==x2:
#     #FIXME: is this enough or do we need to actually remove the domain?
#     y1 = math.ceil(y1)
#     return e1,(0,y1),e2
#   y1 = math.ceil(y1)
#   y2 = math.ceil(y2)
#   m=(y2-y1)/(x2-x1)
#   b=y1-m*x1
#   return e1,(m,b),e2
# mask.apply_domains(discretize)

#discretize the slopes of linear functions, and times to nearest grain (floor). we do this only because z3 optimize doesn't seem to do well with complex rational constants -- for mysterious reasons. 
def discretize_slopes_helper(e1,v,e2):
  # e1=Edge(inf_floor(e1.val),e1.side)
  # e2=Edge(inf_floor(e2.val),e2.side)
  m,b = v
  if b == math.inf:
    return e1,v,e2
  x1=e1.val
  x2=e2.val 
  y1 = m*x1 + b
  y2 = m*x2 + b     
  if x1==x2:
    #FIXME: is this enough or do we need to actually remove the domain?
    # y1 = math.ceil(y1)
    return e1,(0,y1),e2
  if x1 == -math.inf or x2 == math.inf:
    #when we are at the open domains on the sides we don't need to adjust the slope:
    new_m=m
  else:
    #adjust slope to interpolate the end points:
    new_m=(y2-y1)/(x2-x1)
  new_m = (1 if new_m>=0 else -1)*math.ceil(abs(new_m)*100)/100
  # print(f"slope rounding: {m} to {new_m}")
  if x1 == -math.inf:
    if x2 == math.inf:
      new_b=b
    else:
      new_b=y2-new_m*x2
  else:
    new_b=y1-new_m*x1
  # print(f"discretization cost error {new_m*x2+b-y2}, percent error {100*(new_m*x2+b-y2)/y2 if y2!=0 else 'nan'}")
  return e1,(new_m,new_b),e2

def discretize_slopes(mask):
  mask.apply_domains(discretize_slopes_helper)

def bin_max(mask,basetime):
  def bin_max_helper(e1,v,e2):
    m,b = v
    if m==0 or b==math.inf:
      return e1,v,e2    
    y1=m*(e1.val-basetime).total_seconds()+b if e1.val!=-math.inf else 0
    y2=m*(e2.val-basetime).total_seconds()+b if e2.val!=math.inf else 0
    return e1,(0,max(y1,y2)),e2
  mask.apply_domains(bin_max_helper).simplify()

def coarsen_costs(mask,N):
  """merge together costs into N levels and then simplify
  FIXME: only do constant fns"""
  def tc(d,k):
    return tc(d,d[k]) if k in d.keys() and k!=d[k] else k
    
  levels = list(set(d[1] for d in mask.data[::2] if d!=(0,0)))
  levels.sort()
  cost_map={0:0}
  #iteratively choose closest levels to merge, add to mapping
  while len(levels)>=N:
    #find two closest levels
    diffs=[c2-c1 for c1,c2 in zip(levels[:-1],levels[1:])]
    i=diffs.index(min(diffs))
    #map lower cost into upper cost:
    cost_map[levels[i]]=levels[i+1]
    del levels[i]
  #add remaining costs to map as themselves
  for c in levels:
    cost_map[c]=c
  #now apply the mapping to the mask
  mask.apply(lambda p: (p[0],tc(cost_map,p[1])))

def find_bin(mask,t):
  data = [Edge(-math.inf,Topo.RIGHT)]+mask.data+[Edge(math.inf,Topo.LEFT)]
  for e1,e2 in zip(data[:-1:2],data[2::2]):
    # if e1.val==t or e2.val==t:
    #   print(f"e1 {e1}: {repr(e1.side)} {type(e1.side)}, {repr(Topo.RIGHT)} {type(Topo.RIGHT)}, {e1.side == Topo.RIGHT} {type(e1.side)==type(Topo.RIGHT)}") 
    #   print(f"e2 {e2}: {repr(e2.side)} {type(e2.side)}, {repr(Topo.LEFT)} {type(Topo.LEFT)}, {e2.side == Topo.LEFT} {type(e2.side)==type(Topo.LEFT)}") 
    left = e1.val<t or (e1.side==Topo.RIGHT and e1.val==t)
    right = e2.val>t or (e2.side==Topo.LEFT and e2.val==t)
    if left and right:
      return e1,e2


if __name__ == '__main__':

  m=PWfn(False, Edge(1), True, Edge(2.3), False)
  n=PWfn(False, Edge(2), True, Edge(4), False)

  m.combine(n,lambda x,y: x and y)
  assert m == PWfn(False,Edge(2),True,Edge(2.3),False), m
  
  n.apply(lambda x: not x)
  assert n == PWfn(True, Edge(2), False, Edge(4), True), m

  m=PWfn(False, Edge(1), True, Edge(2), False)
  n=PWfn(False, Edge(2), True, Edge(4), False)
  m.combine(n,lambda x,y: x and y)
  assert m == PWfn(False), m

  # print(m.eval(0),m.eval(2),m.eval(2.1),m.eval(2.3),m.eval(3))

  p=PWfn(-1,Edge(0),0.1,Edge(2),0.2,Edge(3),-1)
  strIf = lambda x,y,z: f"If({x},{y},{z})"
  # print(p.abstract_eval(-1, If = strIf, fn=lambda x: x+1)) 
    # p.eval(0),p.eval(1), p.eval(2), p.eval(2.5), p.eval(3))

  x=PWlinear(math.inf,Edge(1,Topo.RIGHT),0,Edge(2,Topo.LEFT),math.inf)
  y=PWlinear(0,Edge(1,Topo.LEFT),math.inf,Edge(2,Topo.RIGHT),0)
  x.plus(y)
  # print(x)

  x=PWlinear(0,Edge(1,Topo.LEFT),1)
  y=PWlinear(0,Edge(1,Topo.RIGHT),4)
  z=PWlinear(1,Edge(1,Topo.LEFT),3)
  print(f"x {x}\ny {y},\nz {z}")
  # z=PWlinear(0,Edge(1,Topo.RIGHT),4,Edge(1,Topo.LEFT),5)
  y.plus(x)
  print(f"x+y {y}")
  y.plus(z)
  print(f"x+y+z {y}")

  # now=datetime.utcnow()
  # print(mk_path((now,0),(now+timedelta(hours=1),1), (now+timedelta(hours=2),1), (now+timedelta(hours=3),0), basetime=now))

  # m=Mask([1, True, 2.3], False)
  # n=Mask([2,True,4],False)
  # m.combine(n,lambda x,y: x and y)
  # print(m)
  # print(m.eval(0),m.eval(2),m.eval(2.1),m.eval(2.3),m.eval(3))

  # p=Mask([0,0.1,2,0.2,3],-1)
  # print(p.eval(-1),p.eval(0),p.eval(1), p.eval(2), p.eval(2.5), p.eval(3))

  # n.apply(lambda x: not x)
  # print(n)


