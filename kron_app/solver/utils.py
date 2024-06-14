##Utils for solver and friends
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import math

##setup Sorts 
# Time = INT
# Time = REAL 
# constant = ps.Int if Time == INT else ps.Real

#FIXME: it'd be a lot clearer if all time intervals were represented as start + length 
#  instead of a some being start + end.
#  cleanest would be to have internal be start,length and make getter/setter for end
#  for each interval.

##classes for data validation
#Note: we treat ids (meeting and user) as str, they will be converted from int...
#TODO: i think we can build these types directly from the db orm if we want to (eg https://fastapi.tiangolo.com/tutorial/sql-databases/)
class FloatMeeting(BaseModel):
  id: str #unique id for this meeting.
  attendees: List[str] #a list of userids.
  optionalattendees: Optional[List[str]] = [] #list of userids, if any.
  optionalattendeepriorities: Optional[Dict[str,int]] = [] #list of priorities, if any.
  # window: list[datetime,datetime] #a pair of [start, end] datetimes in which this meeting must occur.
  window_start: datetime
  window_end: datetime
  freeze_horizon: timedelta = timedelta(hours=0)
  length: timedelta #the (minimum) length of the meeting.
  priority: Optional[int] = None #If this is an int the meeting is optional, value gives soft priority.
  is_optional: bool = False
  is_fixed: bool = False
  final: bool = False
  draft_start: Optional[datetime] #keep draft start if any for setting window of final meetings
  repair_prefs: str = "extend"
  class Config:
    orm_mode = True

# class DraftMeeting(FloatMeeting):
#   start: datetime #add start time!
#   end: datetime #add end time!
#   actualattendees: List[str] #add actual attendees scheduled to be at this meeting

# class FixedMeeting(BaseModel):
#   attendees: List[str] #a list with just one userid.
#   optionalattendees: Optional[List[str]] = []
#   id: str
#   start: datetime #the fixed starting time of this meeting.
#   length: timedelta
#   priority: Optional[int] = None
#   is_optional: bool = False
#   is_fixed: bool = True
#   @property
#   def end(self):
#     return self.start+self.length
#   class Config:
#     orm_mode = True


# #helper make_meetings_df connverts from a list of fixed meetings and a list of float meetings.
# #default grain is 900sec = 15min as the schedule buckets to use.
# def make_meetings(floatmeetings : List[FloatMeeting], basetime : datetime, now : datetime, grain : int =900):
#   #convert times to basetime = 0 integers with some granularity
#   #must provide now datetime

#   floatmeetings = copy.deepcopy(floatmeetings)

#   for m in floatmeetings:
#     #impose constraint that meetings are after now+freeze:
#     m.window_start = max(m.window_start, now+m.freeze_horizon)
#     #shift to internal times:
#     m.window_start = (m.window_start-basetime).total_seconds()/grain
#     m.window_end = (m.window_end-basetime).total_seconds()/grain
#     m.length = m.length.total_seconds()/grain
#     #discretize:
#     #TODO: it seems that the solver doesn't handle float values well, even with REAL type, so
#     #  we discretize in all cases. In principle should only do so for INT... 
#     # if Time == INT:
#     m.window_start = math.floor(m.window_start)
#     m.window_end = math.ceil(m.window_end)
#     m.length = math.ceil(m.length)

#   # for m in fixedmeetings:
#   #   #discretize into internal time:
#   #   end=m.start+m.length
#   #   end=(end-basetime).total_seconds()/grain
#   #   m.start=(m.start-basetime).total_seconds()/grain
#   #   # if Time == INT:
#   #   m.start = math.floor(m.start)
#   #   end=math.ceil(end)
#   #   m.length = end - m.start

#   return floatmeetings

#convert back to time
def convert_to_datetime(t,basetime,grain=900):
  return timedelta(seconds = grain * math.floor(t)) + basetime

# def convert_to_timedelta(t,grain=900):
#   print(t)
#   return timedelta(seconds = grain * math.floor(t))

#convert back from the internal meetings df to something for the rest of the system
#this includes dropping the fixed meetings, converting back to datetimes, 
# def make_drafts(draftmeetings, basetime, grain=900):  
#   unschedueled_ids = [m['id'] for m in draftmeetings if m['time']=="unscheduled"]
#   draftmeetings = [m for m in draftmeetings if m['time']!="unscheduled"]
#   draftmeetings = [DotDict({'id':m.id,
#                   'start':convert_to_datetime(m['time'][0],basetime, grain=grain),
#                   'end':convert_to_datetime(m['time'][1],basetime, grain=grain),
#                   'actualattendees':m.actualattendees}) for m in draftmeetings]
#   return draftmeetings, unschedueled_ids

  # for m in draftmeetings: 
  #   m['start'] = convert_to_datetime(m['time'][0],basetime, grain=grain)
  #   if m['start'].minute%15 != 0:
  #     print(f"!!!!tried to schedule a meeting off 15min grid.")
  #   m['end'] = convert_to_datetime(m['time'][1],basetime, grain=grain) 
  #   # m['window_start'] = convert_to_datetime(m['window'][0],basetime,grain=grain)
  #   # m['window_end'] = convert_to_datetime(m['window'][1],basetime,grain=grain)
  #   m['length'] = m['end']-m['start']
  # return [DraftMeeting(**m) for m in draftmeetings], unschedueled_ids

