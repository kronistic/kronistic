import datetime
import pysmt.shortcuts as ps
from kron_app.solver.solver import make_attendees, make_time, make_window, Interval, get_constraints
from kron_app.solver.utils import convert_to_timedelta, make_meetings, Time, constant

#utilities used below for computing count of nonzero variables and sum in dict
def count(x):
  return ps.Plus([ps.Ite(ps.Equals(e,constant(0)), constant(0), constant(1)) for e in x.values()])

def total(x):
  return ps.Plus(x.values())

def min_count(x,solver):
  n=len(x)
  while True:
      result = solver.solve([count(x)<constant(n)])
      if result:
          n=n-1
      else:
          n=n+1
          solver.add_assertion(count(x)<constant(n))
          solver.solve()
          return n

def min_total(x,solver):
    #first get amount of extension in existing solution, to inintialize bound
    model = solver.get_model()
    m=sum([model.get_py_value(e) for e in x.values()])
    #now lower until unsat
    while True:
        result = solver.solve([total(x)<=constant(m)])
        if result:
            m=m-1
        else:
            m=m+1
            solver.add_assertion(total(x)<=constant(m))
            solver.solve()
            return m

##repair by finding fewest, smallest window extensions:
def extend_windows(floaties, fixies, candidate_ids, now):
  basetime = min([m.window_start for m in floaties])
  floaties, fixies = make_meetings(floaties,fixies,basetime,now)

  #set up hard scheduling problem as usual, except add an extra amount to candidate meetings window_end
  floaties=[m.dict() for m in floaties]
  fixies=[m.dict() for m in fixies]

  #convert window to internal Interval class
  #  if there's no window assume fixed time and use time field as interval
  extensions = {}
  def make_window(row):
    start = row['window_start']
    length = row['window_end']-row['window_start']
    e = ps.Symbol(row['id']+"extension", Time) if row['id'] in candidate_ids else constant(0)
    extensions[row['id']]=e
    return Interval(start,length+e, name=row['id']+"window")
  
  #convert window to internal Interval class
  for m in floaties: m['window']=make_window(m)

  #add time interval variables for floating meetings to schedule
  for m in floaties+fixies: m['time']=make_time(m)

  #convert attendees into Set class
  for m in floaties+fixies: m['actualattendees'] = make_attendees(m)

  with ps.Solver(name="z3") as solver:

    a=get_constraints(floaties,fixies)
    for x in a: solver.add_assertion(x)

    # for a in solver.assertions: print(a)

    #add the constraint that extensions are positive:
    for e in extensions.values(): solver.add_assertion(ps.GE(e,constant(0)))

    ##run the solver (on hard constraints)
    result = solver.solve()
    assert(result) #if there is no sat with extensions we have trouble...

    #first minimize number of extensions
    min_count(extensions,solver)

    #now minimize the total amount of extensions (subject to count constraint)
    min_total(extensions,solver)

    model = solver.get_model()

    extensions = {k:model.get_py_value(v) for k,v in extensions.items()}
    extensions = {k: convert_to_timedelta(v) for k,v in extensions.items() if v!=0}

    return extensions


# ##repair by finding fewest, smallest length decreases:
# def shorten_meetings(meetings_df, candidate_ids, now):
#   #set up hard scheduling problem as usual, except add an extra amount to candidate meetings window_end
#   Time = time_type

#   print("set up meetings_df..")
 
#   #convert window to internal Interval class
#   meetings_df['window']=meetings_df.apply(make_window, axis=1)

#   #convert attendees into Set class
#   meetings_df['actualattendees'] = meetings_df.apply(make_attendees, axis=1)

#   #add time interval variables for floating meetings to schedule

#   reductions = {}
#   def make_time(row):
#     start = row['start'] if row['is_fixed'] else ps.Symbol(row['meetingid']+"start", Time)
#     r = ps.Symbol(row['meetingid']+"extension", Time) if row['meetingid'] in candidate_ids else constant(0)
#     reductions[row['meetingid']]=r    
#     return Interval(start, row['length']-r, optional= row['is_optional'], name=row['meetingid'])

#   meetings_df['time'] = meetings_df.apply(make_time,axis=1)

#   with ps.Solver(name="z3") as solver:

#     add_constraints(meetings_df,solver,now=now)

#     # for a in solver.assertions: print(a)

#     #add the constraint that reductions are positive but less than whole meeting length:
#     for i,row in meetings_df.iterrows():
#       r = reductions[row['meetingid']]
#       solver.add_assertion(ps.GE(r,constant(0)))
#       solver.add_assertion(r<constant(row['length']))

#     ##run the solver (on hard constraints)
#     result = solver.solve()
#     #if there is no solution then this schedule can't be made sat by reducing meetings
#     if not result:
#       print("this schedule can't be made sat by reducing meetings!")
#       return result

#     #first minimize number of reductions
#     min_count(reductions, solver)

#     #now minimize the total amount of extensions (subject to count constraint)
#     min_total(reductions, solver)

#     model = solver.get_model()

#     # meetings_df['time'] = meetings_df['time'].apply(lambda r: r.make_concrete(model))
#     # meetings_df['window'] = meetings_df['window'].apply(lambda r: r.make_concrete(model))
#     # meetings_df['actualattendees']=meetings_df['actualattendees'].apply(lambda r: r.make_concrete(model))
#     # print("schedule after extensions:")
#     # print(meetings_df)

#     return {k:model.get_py_value(v) for k,v in reductions.items()}

