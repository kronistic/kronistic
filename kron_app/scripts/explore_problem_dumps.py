import argparse
from copy import deepcopy
# from copy import deepcopy
from math import inf
import math
import multiprocessing
import pickle
import threading
from time import process_time, time
from kron_app.mask_utils import PWlinear,Edge,Topo
import datetime
# from kron_app.solver.solver_experimental import solver
from kron_app.solver.solver import solver
from numpy import corrcoef, mean
from kron_app.solver.utils import FloatMeeting
from kron_app.utils import DotDict
import matplotlib.pyplot as plt

def load_problem(r):
  floaties = r['floaties']
  masks = r['masks']
  result, draftmeetings, unschedueled_ids, result_code=r['result']

  #eval all the mask reprs:
  masks = DotDict({id:{k:{t:eval(w) for t,w in v.items()} for k,v in u.items()} for id,u in masks.items()})

  #eval the datetime strings:
  for f in floaties:
    f['window_start']= eval(f['window_start'])
    f['window_end']=eval(f['window_end'])
    f['freeze_horizon']=eval(f['freeze_horizon'])
    f['length']=eval(f['length'])
    if f['draft_start'] is not None:
      f['draft_start']=eval(f['draft_start'])
  
  #eval the schedule datetimes:
  if draftmeetings:
    for d in draftmeetings:
      d['start']=eval(d['start'])
      d['end']=eval(d['end'])

  #read time params from log:
  basetime=eval(r['basetime'])
  now=eval(r['now'])

  return floaties,masks,now,basetime,draftmeetings

def load_overlapping(r):
  overlapping = r['overlapping']
  #eval the datetime strings:
  for id,neighbors in overlapping.items():
    for f in neighbors['fixed']:
      f['start_at']=eval(f['start_at'])
      f['end_at']=eval(f['end_at'])
    for f in neighbors['float']:
      f['start_at']=eval(f['start_at'])
      f['end_at']=eval(f['end_at'])
  return overlapping

def mask_cplx(mask):
  return (len(mask.data[1::2]), len(set(mask.data[::2])))

def inspect_log(logfile='solver_log.pickle',show_floaties=False,show_prov=False):
  with open(logfile, 'rb') as f:
    runs = pickle.load(f)

  for i,r in enumerate(runs):
    print(f"{i}: result {r['result_code']}, time {r['cputime']}, {r['problem_size']} floaties")

    if show_prov:
      print(f"problem provenances {r['problem_prov']}")

    if show_floaties:
      floaties,masks,now,basetime,schedule=load_problem(r)
      for id,u in masks.items():
        hard_mask = u.masks.hard
        hardmask_cplx = mask_cplx(hard_mask)
        hard_mask.plus(u.masks.ifneeded).plus(u.masks.sooner).simplify()
        allmask_cplx = mask_cplx(hard_mask)
        m=next((f for f in floaties if f['id']==id), None)
        s=next((x for x in schedule if x['id']==id), None) if schedule else None  
        if m:
          print(f"  {'optional' if m['is_optional'] else ''} floaty {id}, hard mask complexity {hardmask_cplx}, all mask complexity {allmask_cplx}, {len(m['attendees'])} attendees, window length {(m['window_end']-m['window_start']).days}, scheduled at {s['start'] if s else 'never'}")

def stats(logfile):
  with open(logfile, 'rb') as f:
    runs = pickle.load(f)
  
  runtimes=[]
  problem_sizes=[]
  attendees=[]
  wlengths=[]
  allmask_edges=[]
  allmask_levels=[]
  foldop = sum
  for i,r in enumerate(runs):
    runtimes.append(math.log(r['cputime']))
    problem_sizes.append(r['problem_size'])
    # print(f"{i}: result {r['result_code']}, time {r['cputime']}, {r['problem_size']} floaties")

    floaties,masks,now,basetime,schedule=load_problem(r)
    masks = {id:u for id,u in masks.items() if id in [f['id'] for f in floaties]}
    for id,u in masks.items():
      u.masks.hard.plus(u.masks.ifneeded).plus(u.masks.sooner).simplify()

    attendees.append(foldop([len(f['attendees']) for f in floaties]))
    wlengths.append(foldop([(f['window_end']-f['window_start']).days for f in floaties]))
    allmask_edges.append(foldop([mask_cplx(u.masks.hard)[0] for id,u in masks.items()]))
    allmask_levels.append(foldop([mask_cplx(u.masks.hard)[1] for id,u in masks.items()]))
  
  print("runtimes, problem_sizes, attendees, wlengths, allmask_edges, allmask_levels")
  print(corrcoef([runtimes,problem_sizes,attendees,wlengths,allmask_edges,allmask_levels]))
  plt.plot(problem_sizes,runtimes,'bo')
  plt.show()

def inspect_floaty(run,fid,logfile):
  with open(logfile, 'rb') as f:
    runs = pickle.load(f)
  r=runs[run]

  floaties,masks,now,basetime,schedule=load_problem(r)
  m=next(f for f in floaties if f['id']==fid)
  for k,v in m.items():
    print(f"{k}: {v}")
  mask=masks[fid].masks.hard
  mask.plus(masks[fid].masks.ifneeded).plus(masks[fid].masks.sooner).simplify()
  # print(f"hard mask {masks[fid].masks.hard}")
  # print(f"window mask {masks[fid].masks.window}")
  # print(f"kronduty mask {masks[fid].masks.kronduty}")
  print(f"full mask, complexity {mask_cplx(mask)}: {mask}")

def check_conflicts(run,logfile):
  with open(logfile, 'rb') as f:
    runs = pickle.load(f)
  r=runs[run]

  floaties,masks,now,basetime,schedule=load_problem(r)
  overlapping = load_overlapping(r)

  #for each floaty get it's overlapping set and see if it actually overlaps
  for f in floaties:
    ov = overlapping[f['id']]
    #any overlapping fixed?
    for o in ov['fixed']:
      if not (f['draft_start'] >= o['end_at'] or f['draft_start']+f['length'] <= o['start_at']):
        if not o['kron_duty']:
          print(f"floaty {f['id']} overlaps fixed {o['id']}")
    #any overlapping floaty?
    for o in ov['float']:
      if not (f['draft_start'] >= o['end_at'] or f['draft_start']+f['length'] <= o['start_at']):
        print(f"floaty {f['id']} overlaps floaty {o['id']}")


def run_solve(floaties,masks,now,basetime,timeout=60000):
  cpustart = process_time()
  result, schedule, unschedueled_ids, result_code=solver(floaties,basetime=basetime,masks=masks,config={'timeout':timeout})
  cputime = round((process_time() - cpustart) * 1000)
  print(f"result {result_code}, runtime {cputime}.")
  print("")

def solve_run(start,end,logfile='solver_log.pickle',timeout=60000,repeat=1):
  with open(logfile, 'rb') as f:
    runs = pickle.load(f)
  
  if end:
    rs=runs[start:end]
  else:
    rs=[runs[start]]


  for i in range(repeat):
    totaltime = time()
    for r in rs:
      floaties,masks,now,basetime,schedule=load_problem(deepcopy(r))

      #turn floaties back into objects:
      floaties = [FloatMeeting(**f) for f in floaties]
      
      #run solver on restored problem:
      #run this part in a fresh python process:
      # Create a new process
      p = multiprocessing.Process(target=run_solve, kwargs={'floaties':floaties,'masks':masks,'now':now,'basetime':basetime,'timeout':timeout})
      # Start the new process
      p.start()
      # # Send data to the new process
      # queue.put(floaties)
      # Wait for the new process to finish
      p.join()


    print(f"total run time: {round((time() - totaltime) * 1000)}\n\n")

def timeuse_stats(logfile):
  with open(logfile, 'rb') as f:
    timeuse = pickle.load(f)
  
  # print(timeuse)
  plt.hist(timeuse)
  plt.show()
  """note: empirically it looks like this distribution is exponential or maybe somethign heavy tailed. many users have less than an hour of busy time (on average over all days, incl weekends), while a few have 4-5hrs per day (which probably means more like 6 on weekdays?)."""



  # #run solver on restored problem:
  # solver(floaties,[],now,basetime,masks=masks)

  # #run solver on restored problem, minus ifneeded:
  # for id,u in masks.items():
  #   for k,v in u.items():
  #     v.ifneeded=PWlinear(0)
  # solver(floaties,[],now,basetime,masks=masks)

  # #run solver on restored problem, with ifneeded converted to step fn:
  # def bin_mean(e1,v,e2):
  #   m,b = v
  #   if m==0 or b==inf:
  #     return e1,v,e2    
  #   y1=m*(e1.val-basetime).total_seconds()+b if e1.val!=-inf else 0
  #   y2=m*(e2.val-basetime).total_seconds()+b if e2.val!=inf else 0
  #   return e1,(0,(y1+y2)/2),e2

  # def bin_max(e1,v,e2):
  #   m,b = v
  #   if m==0 or b==inf:
  #     return e1,v,e2    
  #   y1=m*(e1.val-basetime).total_seconds()+b if e1.val!=-inf else 0
  #   y2=m*(e2.val-basetime).total_seconds()+b if e2.val!=inf else 0
  #   return e1,(0,max(y1,y2)),e2

  # for id,u in masks.items():
  #   u.masks.ifneeded.apply_domains(bin_max).simplify()
  #   print(f"{id} {len(u.masks.ifneeded.data)}")



if __name__ == '__main__':

  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest='command', required=True)
  
  parser_inspect = subparsers.add_parser('inspect', help='Display log runs info.')
  # parser_inspect.add_argument('logfile',nargs='?',default='solver_log.pickle')
  parser_inspect.add_argument('-l', '--logfile',default='solver_log.pickle')
  parser_inspect.add_argument('-f', '--show_floaties',action='store_true')
  parser_inspect.add_argument('-p', '--show_prov',action='store_true')

  parser_inspect.set_defaults(fn=inspect_log)

  parser_stats = subparsers.add_parser('stats', help='Correlate things...')
  # parser_inspect.add_argument('logfile',nargs='?',default='solver_log.pickle')
  parser_stats.add_argument('-l', '--logfile',default='solver_log.pickle')
  parser_stats.set_defaults(fn=stats)

  parser_floaty = subparsers.add_parser('floaty', help='Show a floaty from a given run.')
  parser_floaty.add_argument('run', type=int)
  parser_floaty.add_argument('fid')
  # parser_floaty.add_argument('logfile',nargs='?',default='solver_log.pickle')
  parser_floaty.add_argument('-l', '--logfile',default='solver_log.pickle')
  parser_floaty.set_defaults(fn=inspect_floaty)

  parser_conflicts = subparsers.add_parser('conflicts', help='Show conflicts from a given run that has overlapping dump.')
  parser_conflicts.add_argument('run', type=int)
  # parser_conflicts.add_argument('logfile',nargs='?',default='solver_log.pickle')
  parser_conflicts.add_argument('-l', '--logfile',default='solver_log.pickle')
  parser_conflicts.set_defaults(fn=check_conflicts)

  parser_solve = subparsers.add_parser('solve', help='Run solver on a logged problem.')
  parser_solve.add_argument('start', type=int)
  # parser_solve.add_argument('logfile',nargs='?',default='solver_log.pickle')
  parser_solve.add_argument('-l', '--logfile',default='solver_log.pickle')
  parser_solve.add_argument('-t', '--timeout', type=int, default=60000)
  parser_solve.add_argument('-e', '--end', type=int)
  parser_solve.add_argument('--repeat', type=int, default=1)
  parser_solve.set_defaults(fn=solve_run)

  parser_timeuse = subparsers.add_parser('timeuse', help='Display how busy people were.')
  # parser_inspect.add_argument('logfile',nargs='?',default='solver_log.pickle')
  parser_timeuse.add_argument('-l', '--logfile',default='time_usage.pickle')
  parser_timeuse.set_defaults(fn=timeuse_stats)

  args = parser.parse_args()
  args.fn(**{k:v for k,v in vars(args).items() if not k in ['command', 'fn']})

 

  """
  TODO: 
    -if we turn off ifneeded does it sat? yes, and very very fast.
    -try stepwise ifneeded masks
      -as cost. mean doesn't seem to help... max does help -- many fewer bins.
      -as separate tiers of objective: ifneeded before sooner is 20x faster. 
      -with pseudo-booleans?
    -write our own max search for ifneeded? by thresholding and plus w hard can avoid any reasoning... but not incremental.
    -does simplifying lower bounds matter?
  """