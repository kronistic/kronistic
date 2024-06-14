# import pysmt.shortcuts as ps
# from copy import deepcopy
import copy
from time import process_time
import z3 
from kron_app.utils import DotDict 
from datetime import datetime, timedelta
import math
from kron_app.mask_utils import Edge, Topo, find_bin, bin_max, coarsen_costs, discretize_slopes
from kron_app.utils import dictunion

Time = z3.RealSort()
constant = lambda x: float(x) #FIXME: does z3 have a constant constructor i should use?
#TODO: this simple def should work, but doesn't so i use the If hack..
# z3zero=z3.z3num.Numeral(0.0)
z3zero=z3.If(True,0,0)

# ps.Bool(x) -> x
# ps.Symbol(x) -> z3.Bool(x)
# ps.Symbol(x,T) -> z3.Const(x,T)
# solver.add_assertion(x) -> solver.add(x)
# solver.get_model -> solver.model
# model.get_py_value(x) -> python_num(x,model)
# ps.LE -> <=
# ps.GE -> >=
# ps.Equals -> ==
# solver.solve -> solver.check
# ps.Ite -> z3.If


#
# need to setup z3 paths:
#
# export PYTHONPATH=~/z3/bin/python
# export DYLD_LIBRARY_PATH=$DYLD_LIBRARY_PATH:~/z3/bin 
#


#solver core using z3 with Optimize for soft objectives.
#
# Note: there is no max planning horizon, but all events must fall in their finite window.
#
# TODO: handle locations
# TODO: add solver hints, such as time-available>time-required constraints?

#The ontology here consists of: 
#  people, sets of people with some members optionally included, 
#  times, time intervals that can exist or not (for optionality),
#  locations, location set in which one is the actual location



#helper to turn z3 values into python ones
def python_num(x,model):
  if not isinstance(x,(z3.ArithRef,z3.BoolRef)):
    return x
  v=model.eval(x)
  return python_num_raw(v)

def python_num_raw(v):
  if z3.is_int_value(v):
    return v.as_long()
  if z3.is_algebraic_value(v):
    v = v.approx(2)
  if z3.is_rational_value(v):
    return float(v.numerator_as_long())/float(v.denominator_as_long())
  return z3.is_true(v)

#simple helper class for time intervals:
class Interval:
  def __init__(self, start, length, optional=False, name="interval"):
    self.start = constant(start) if isinstance(start, (int, float)) else start 
    self.length = (constant(length) if isinstance(length, (int, float)) else length)
    # self.end = self.start + (constant(length) if isinstance(length, (int, float)) else length) 
    self.exist = True if not optional else z3.Bool(name+"exist") 

  def __str__(self):
    return "(% s, % s)" % (self.start,self.end) if self.exist else "unscheduled"

  def empty_intersect(self, other):
    #check if interection of self with other is empty
    #this happens if one interval ends before other starts
    #or either interval doesn't exist
    return z3.Or(z3.Not(self.exist),z3.Not(other.exist), self.end <= other.start, other.end <= self.start)

  def contains(self, other):
    #check if self fully contains other, or either doesn't exist.
    return z3.Or(z3.Not(self.exist),z3.Not(other.exist), 
                z3.And( self.start <= other.start, self.end >= other.end))

  def make_concrete(self,model):
    self.exist = self.exist if isinstance(self.exist, bool) else  python_num(self.exist,model)
    if self.exist:
      self.start = self.start if isinstance(self.start, (int, float)) else python_num(self.start,model)
      # self.end = self.end if isinstance(self.end, (int, float)) else python_num(self.end,model)
      self.length = self.length if isinstance(self.length, (int, float)) else python_num(self.length,model)
      return [self.start, self.end]
    else:	
      return "unscheduled"

  @property
  def end(self):
    return self.start+self.length
  # @property
  # def length(self):
  #   return self.end-self.start


class Set:
  def __init__(self, fixedelts, optionalelts=[], name="set"):
    #convert into dict of key = elt, val = bool inclusion indicator
    self.elts = dictunion({e:True for e in fixedelts}, {e:z3.Bool(e+name+"included") for e in optionalelts})

  def __str__(self):
    return str(self.elts)

  def contains(self,item):
    """can't use __contains__ to overload 'in' op because that tries casting to bool"""
    if item in self.elts.keys():
      return self.elts[item]
    else:
      return False

  def any_intersect(self, other):
    tmp = [z3.And(v,other.elts[k]) for k,v in self.elts.items() if k in other.elts]
    return False if len(tmp) == 0 else z3.Or(tmp)

  #check if the two sets could ever have an intersection, based on support sets
  def could_intersect(self, other):
    return set(self.elts.keys()) & set(other.elts.keys())

  #return the number of set elements that are included
  def count(self):
    return sum(z3.If(v,constant(1),constant(0)) for v in self.elts.values())

  def make_concrete(self,model):
    # self.elts = {k: (v if isinstance(v,bool) else python_num(model[v])) for k,v in self.elts.items()}
    # self.elts = {k: model.get_py_value(v) for k,v in self.elts.items()}
    self.elts = [k for k,v in self.elts.items() if python_num(v,model)]
    return self.elts

# def make_window(row):
#   start = row['window_start']
#   length = row['window_end']-row['window_start'] #if not row['window_end'] is None else z3.Const(row['id']+"windowlength", Time)
#   return Interval(start, length, name=row['id']+"window")

def make_time(row):
  start = z3.Const(row['id']+"start", Time)
  return Interval(start, row.length, optional= row.is_optional, name=row.id)

def make_attendees(row):
  return Set(row['attendees'],row['optionalattendees'],name=row['id'])

# def get_constraints(floaties,fixies):
#   #constraint that meeting occurs in its time window:  
#   a=[]
#   for r in floaties:
#     a.append(r['window'].contains(r['time']))

#   # #add constraint that any variable window lengths are >0
#   # for r in floaties:
#   #   if row['window_end'] is None:
#   #     a.append(row['window'].length > constant(0))

#   #fundemental schedule axiom: 
#   #  forall meeting:m1 forall meeting:m2 intersect(attendees(m1), attendees(m2)) => not intersect(time(m1),time(m2))
#   # note that empty_intersect will be true if either meeting doesn't exist (isn't going to be scheduled).
#   for r in floaties:
#     for s in fixies:
#       #TODO: can further narrow this to cases where r window overlaps s
#       if r['actualattendees'].could_intersect(s['actualattendees']): 
#         ax = z3.Implies(r['actualattendees'].any_intersect(s['actualattendees']), 
#                         r['time'].empty_intersect(s['time']) )
#         a.append(ax)

#   for r in floaties:
#     for s in floaties:
#       if r==s: break
#       #TODO: can further narrow this to cases where r and s windows overlap.
#       if r['actualattendees'].could_intersect(s['actualattendees']): 
#         ax = z3.Implies(r['actualattendees'].any_intersect(s['actualattendees']), 
#                         r['time'].empty_intersect(s['time']) )
#         a.append(ax)

#   return a

def kron_solver(floaties, config, masks):
  # solvestart = process_time()

  floaties=[DotDict(m.dict()) for m in floaties]

  # solver = z3.Optimize()
  # z3.set_param(verbose=1)
  # solver.set("timeout", 100)
  # solver.set("solver2_timeout", 1000)
  # solver = z3.SolverFor("QF_LIA") 
  # solver = z3.SolverFor("QF_LRA") 

  #add time interval variables for floating meetings to schedule
  for m in floaties: m.time=make_time(m)

  #convert attendees into Set class
  for m in floaties: m.actualattendees = make_attendees(m)

  constraints=[]

  #impose non-overlap constraint on floaties:
  for r in floaties:
    for s in floaties:
      if r==s: break
      #TODO: can further narrow this to cases where r and s windows overlap.
      if r.actualattendees.could_intersect(s.actualattendees): 
        ax = z3.Implies(r.actualattendees.any_intersect(s.actualattendees), r.time.empty_intersect(s.time) )
        constraints.append(ax)

  #impose constraint that scheduled meetings have at least one attendee
  for r in floaties:
    constraints.append(z3.Implies(r.time.exist, r.actualattendees.count() > constant(0)))

  #soft constraint that optional meetings should be scheduled and that optional attendees are present
  optionalmtgs=0 #z3zero
  optionalmtgs_max=0
  optionalatt=0 #z3zero
  for r in floaties:
    if r.is_optional: 
      optionalmtgs += z3.If(r.time.exist,constant(r.priority),constant(0)) 
      optionalmtgs_max += r.priority
      #add small penalty for not scheduling meetings with draft_start (ie previously scheduled meetings)
      if r.draft_start is not None: 
        optionalmtgs += z3.If(r.time.exist,constant(10),constant(0))
        optionalmtgs_max += 10
      

    if len(r.optionalattendees) != 0:
      optionalatt_a = 0
      optionalatt_max = 0
      for a in r.optionalattendees:
        optionalatt_a += z3.If(r.actualattendees.contains(a),constant(r.optionalattendeepriorities[a]),constant(0))
        optionalatt_max += r.optionalattendeepriorities[a]
      #normalize... the optionalatt score is between 0 and 1
      #should consider if the relative weight wrt optional meetings matters.
      optionalatt += optionalatt_a/optionalatt_max 
    # if len(r.optionalattendees) != 0:
    #   print(r.optionalattendeepriorities)
    #   optionalatt_count = r.actualattendees.count() - constant(len(r.attendees))
    #   optionalatt += optionalatt_count/len(r.optionalattendees)
    #   optionalatt_max += len(r.optionalattendees)
  
  optatt_cost=0 #z3zero
  cost=0
  for m in floaties:
    step_mask=copy.deepcopy(masks[m.id].masks.hard)
    ifneeded_mask=masks[m.id].masks.ifneeded
    sooner_mask=masks[m.id].masks.sooner
    step_mask.plus(ifneeded_mask).plus(sooner_mask)

    def bin_mean_helper(e1,v,e2):
      m,b = v      
      if math.isinf(b):
        return e1,(0,b),e2
      y1=m*(e1.val)+b if math.isfinite(e1.val) else 0
      y2=m*(e2.val)+b if math.isfinite(e2.val) else 0
      return e1,(0,round((y1+y2)/2),2),e2
    step_mask.apply_domains(bin_mean_helper).simplify()

    allowed_start = step_mask.abstract_eval(m.time.start,If=z3.If,fn=lambda is_inf,y: not is_inf) 
    constraints.append(z3.If(m.time.exist,allowed_start,True)) 
    penalty = step_mask.abstract_eval(m.time.start,If=z3.If,fn=lambda is_inf,y: 0 if is_inf else y)
    cost += z3.If(m.time.exist,-penalty,0)

    for u in m.optionalattendees:
      mask=copy.deepcopy(masks[m.id].optatt_masks[u])
      mask.apply_domains(bin_mean_helper).simplify()
      allowed_start = mask.abstract_eval(m.time.start,If=z3.If,fn=lambda is_inf,y: not is_inf) 
      constraints.append(z3.If(z3.And(m.time.exist,m.actualattendees.contains(u)), allowed_start, True))
      penalty = mask.abstract_eval(m.time.start,If=z3.If,fn=lambda is_inf,y: 0 if is_inf else y) 
      optatt_cost += z3.If(z3.And(m.time.exist,m.actualattendees.contains(u)), -penalty, 0)

  #soft constraint that meetings should be at their draft start time
  keep_draft_start=0 #z3zero
  for m in floaties:
    # print(m)
    if m.draft_start is not None:
      keep_draft_start += z3.If(m.time.exist, 
              z3.If(m.time.start==m.draft_start,
                constant(10),
                constant(0)),
              constant(0))
      # print(f"keep draft start for {m.id}, {m.draft_start}, {m.time.start==m.draft_start}, {keep_draft_start}")


  #TODO: think through relative costs..
  objectives = []
  optionals_obj=2*optionalmtgs+1*optionalatt
  if not isinstance(optionals_obj,(float,int)):
    # print(f"optionals_obj is {optionals_obj}")
    objectives.append(optionals_obj)
  objectives.append(cost)
  if not isinstance(optatt_cost,(float,int)):
    objectives.append(optatt_cost)
  if not isinstance(keep_draft_start,(float,int)):
    # print(f"keep_draft_start is {keep_draft_start}")
    objectives.append(keep_draft_start) #keep draft start time is lex last
  # print(objectives)
  # print(constraints)
  print("solve with wmax objective")
  result,mod, two_pass = two_pass_optimize(objectives,constraints,config)
  print(f" wmax solve was {result} {'with' if two_pass else 'without'} second pass.")

  if result != z3.sat:
    #We got here if the maxw could't find a model
    result_code = "unsat"+("_2" if two_pass else "_1") if result==z3.unsat else "timeout_timeout"
    return False, None, result_code
  
  #result is sat, so we should have a model (from one pass or the other), now we add constraints that times are in the bins from this model, then add back the origial objective..
  cost=0
  # optatt_cost=0
  keep_draft_start=0
  constraints=[] #we rebuild the hard constraints in simplified form using previous solution
  for m in floaties:
    mexist = m.time.exist if isinstance(m.time.exist, bool) else  python_num(m.time.exist,mod)
    #constrain existence to model we have:
    constraints.append(m.time.exist == mexist)
    #constrain optional attendees to model:
    actual_att = [k for k,v in m.actualattendees.elts.items() if python_num(v,mod)]
    for u in m.optionalattendees:
      constraints.append((u in actual_att) == m.actualattendees.contains(u))

    if mexist:

      #constrain relative times based on first solve
      for p in floaties:
        if m==p:
          break
        pexist = p.time.exist if isinstance(p.time.exist, bool) else  python_num(p.time.exist,mod)
        actual_intersect = [k for k,v in p.actualattendees.elts.items() if python_num(v,mod) and k in actual_att]
        if pexist and actual_intersect:
          if python_num(m.time.end,mod) <= python_num(p.time.start,mod):
            constraints.append(m.time.end<=p.time.start)
          else: 
            constraints.append(p.time.end<=m.time.start)
          # else:
          #   print("!!!events that should have constraint don't")
          #   # print(f"   {mexist} {pexist} {actual_intersect} m start/end:{python_num(m.time.start,mod)} / {python_num(m.time.end,mod)}. p start/end: {python_num(p.time.start,mod)} / {python_num(p.time.end,mod)}")

      #soft constraint that meetings should be at their draft start time
      if m.draft_start is not None:
        keep_draft_start += z3.If(m.time.start==m.draft_start,constant(10),constant(0))
      
      mask=masks[m.id].masks.hard
      #find mask for each optional attendee that is an actual attendee
      for u in m.optionalattendees:
        if u in actual_att:
          mask=mask.plus(masks[m.id].optatt_masks[u])
      #add in ifneeded and sooner masks
      ifneeded_mask=masks[m.id].masks.ifneeded
      sooner_mask=masks[m.id].masks.sooner
      mask.plus(ifneeded_mask).plus(sooner_mask)
      #discretize because LRA solver hates wierd rationals..
      discretize_slopes(mask) 

      #find the bin edges that bound the start time
      e1,e2 = find_bin(mask,python_num(m.time.start,mod))
      
      #find the interval constraints, based on the bin edges
      #constrain only if the bin edge is finite
      if math.isfinite(e2.val):
        if e2.side==Topo.RIGHT:
          ub = m.time.start<e2.val
        else:
          ub = m.time.start<=e2.val
        constraints.append(ub)

      if math.isfinite(e1.val):
        if e1.side==Topo.LEFT:
          lb = m.time.start>e1.val
        else:
          lb = m.time.start>=e1.val
        constraints.append(lb)

      #add the soft penalty for the start time
      penalty = mask.abstract_eval(m.time.start,If=z3.If,fn=lambda is_inf,y: 0 if is_inf else y)
      cost += -penalty

      # for u in m.optionalattendees:
      #   if u in actual_att:
      #     mask=masks[m.id].optatt_masks[u]
      #     discretize_slopes(mask)
      #     penalty = mask.abstract_eval(m.time.start,If=z3.If,fn=lambda is_inf,y: 0 if is_inf else y) 
      #     optatt_cost +=  -penalty

  print("solve with LRA objective")
  lra_objectives = []
  # if not isinstance(optionals_obj,(float,int)):
  #   lra_objectives.append(optionals_obj)
  if not isinstance(cost,(float,int)):
    lra_objectives.append(cost)
  # if not isinstance(optatt_cost,(float,int)):
  #   lra_objectives.append(optatt_cost)
  if not isinstance(keep_draft_start,(float,int)):
    lra_objectives.append(keep_draft_start)
  lra_result, m, lra_two_pass = two_pass_optimize(lra_objectives,constraints,config)
  print(f" LRA solve was {lra_result} {'with' if lra_two_pass else 'without'} second pass.")
  if lra_result==z3.sat:
    #we found a new model, use it. otherwise we have one from the wmax pass but not the LRA pass, so just use the old one.
    mod=m

  # print(f"""  objective values: 
  #   optional meetings: {python_num(optionalmtgs,mod)} / {optionalmtgs_max}, \
  #   optional attendees: {python_num(optionalatt,mod)} / {optionalatt_max}, \
  #   ifneeded: {python_num(ifneeded_cost,mod)}, \
  #   sooner meetings: {python_num(sooner_cost,mod)}""")
  for m in floaties:
    m.time = m.time.make_concrete(mod)
    m.actualattendees = m.actualattendees.make_concrete(mod)

  result_code="sat"+("_2" if two_pass else "_1")+"-lra_"+str(lra_result)+("_2" if lra_two_pass else "_1")
  return True, floaties, result_code


"""
lower and upper bounds are not as expected:
[https://stackoverflow.com/questions/60841582/timeout-for-z3-optimize]

When maximization, the lower bound corresponds to the value of the objective function in the most recent partial solution found by the OMT solver. ...
After a timeout signal occurred when maximizing an obj instance obtained from maximize(), one should be able to retrieve the latest approximation v of the optimal value of obj by calling obj.lower().

i think this means "upper" is actually the lower bound on the objective...
"""

def two_pass_optimize(objectives,constraints=[],config={'timeout':60000}):
  two_pass=False
  solver = z3.Optimize()
  # z3.set_param(verbose=1)
  solver.assert_exprs(constraints)
  # solver.push()
  objs = [solver.maximize(ob) for ob in objectives]
  solver.set("timeout", config['timeout'])  
  cpustart = process_time()
  result=solver.check()
  cputime = round((process_time() - cpustart) * 1000)
  print(f"  optimizer check took {cputime} (timeout {config['timeout']}), result {result}")
  bounds = [(ob.lower(),ob.upper()) for ob in objs]
  print(f"  bounds {bounds}")
  m=solver.model() if result==z3.sat else None

  if result != z3.sat and result != z3.unsat:
    #in this case the solver timed out. we *may* have a lower bound... try imposing the lower bound and solving again (Note must get lower bounds before pop, or risk segfault)
    #Note: it seems that the interval is [upper, lower] when maximizing.
    two_pass=True
    obbo=list(zip(objectives,bounds))
    obbo=[(ob,bo,bo[0]-bo[1]) for ob,bo in obbo]
    # solver.pop()
    # solver.push()
    solver = z3.Solver()
    timeout=math.floor(config['timeout'])
    solver.set("timeout", timeout)
    solver.assert_exprs(constraints)
    ##hard constraints check:
    #impose upper bounds (faster hard check)
    for ob,bo,gap in obbo:
      solver.add(ob<=bo[0])
    cpustart = process_time()
    result=solver.check()
    cputime = round((process_time() - cpustart) * 1000)
    print(f"  hard constraints solver check took {cputime} (timeout {timeout}), result {result}")
    m=solver.model() if result==z3.sat else None
    if result==z3.sat:
      f=1000 #starting multiplier on loosening bounds
      while result==z3.sat and f>0.01:
        for ob,bo,gap in obbo:
          lb=bo[1]-f*gap
          print(f"   using lb {lb}")
          solver.add(ob>=lb)
        cpustart = process_time()
        prevresult=result
        result=solver.check()
        cputime = round((process_time() - cpustart) * 1000)
        print(f"  bound factor {f}, solver check took {cputime} (timeout {timeout}), result {result}")
        m=solver.model() if result==z3.sat else m
        f=f/2 #is this fast enough?
      result=prevresult #set back to last sat (before exiting loop)
  
  # m=solver.model() if result==z3.sat else None
  return result, m, two_pass


####### main entry point to solver
def solver(floaties, basetime: datetime, grain : int =900, masks={}, config = {'timeout': 60000}):
  """now indicates the current time and is used for makeing sure meetings aren't scheduled sooner than their freeze horizon"""  
  if len(floaties)==0:
    return True,[],[], "trivial_problem"

  #this copy is because run_solver reuses the same list when constructing the repair set but we mutate m.length below. we can remove this if we deal with length differently...
  floaties = copy.deepcopy(floaties)

  for m in floaties:
    #shift to internal times:
    #TODO: in solver only Interval still uses length. we could precompute the allowable start time constraints, eg with a relation mask.
    m.length = m.length.total_seconds()/grain
    m.length = math.ceil(m.length)
    #shift draft times to internal times, if not None:
    if m.draft_start is not None:
      m.draft_start = (m.draft_start-basetime).total_seconds()/grain
      m.draft_start = math.floor(m.draft_start)

  def adjust_masks(mask):
    #first we (finish) converting times into grains-from-basetime:
    mask.apply_edges(lambda x: (x-basetime).total_seconds()/grain)
    mask.apply(lambda p: (p[0]*grain,p[1]))
    #push bin edges to even steps (is this needed?)
    mask.apply_edges(lambda x: math.floor(x) if math.isfinite(x) else x)
    # #next we are going to discretize the linear functions: times to nearest grain (floor) and costs to nearest utile (ceil to avoid making a cost zero?). we do this only because z3 optimize doesn't seem to do well with complex rational constants -- for mysterious reasons. 
    # discretize_slopes(mask)

  for mid,m in masks.items():
    # bin_max(m.masks.ifneeded,basetime)
    # coarsen_costs(m.masks.ifneeded,2)
    adjust_masks(m.masks.hard)
    adjust_masks(m.masks.ifneeded)
    adjust_masks(m.masks.sooner)
    for u,mask in m.optatt_masks.items():
      adjust_masks(mask)

  result, schedule_floaties, result_code = kron_solver(floaties,config = config,masks=masks)

  if result:
    unschedueled_ids = [m['id'] for m in schedule_floaties if m.time=="unscheduled"]
    draftmeetings = [m for m in schedule_floaties if m.time!="unscheduled"]
    draftmeetings = [DotDict({'id':m.id,
                  'start':convert_to_datetime(m.time[0],basetime, grain=grain),
                  'end':convert_to_datetime(m.time[1],basetime, grain=grain),
                  'actualattendees':m.actualattendees}) for m in draftmeetings]
    return result, draftmeetings, unschedueled_ids, result_code
  else:
    return result,None,[], result_code

def convert_to_datetime(t,basetime,grain=900):
  return timedelta(seconds = grain * math.floor(t)) + basetime
