import json
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime, timedelta

from kron_app.solver.solver import kron_solver
from kron_app.solver.utils import make_meetings_df

app = FastAPI()


@app.get("/")
def get_root():
  return {"Hello": "World"}

class FloatMeeting(BaseModel):
  attendees: list[str] #TODO: assume users are int? or string?
  meetingid: str #TODO: assume meetingids are int?
  optionalattendees: list[str] | None = None
  window: tuple(datetime,datetime)
  length: timedelta
  priority: int | None = None

class FixedMeeting(BaseModel):
  attendees: list[str] #TODO: assume users are int? or string?
  meetingid: str #TODO: assume meetingids are int?
  start: datetime
  length: timedelta
  priority: int | None = None

class DraftMeeting(BaseModel):
  attendees: list[str] #TODO: assume users are int? or string?
  meetingid: str #TODO: assume meetingids are int?
  optionalattendees: list[str] | None = None
  start: datetime #add start time!
  length: timedelta
  window: tuple(datetime,datetime) | None
  priority: int | None = None

#problem should be json of list of dicts whose fields are specified in solver.py
#response is None if solver fails.. add more informative failure info?
@app.put("/solve", response_model=list[DraftMeeting]|None)
def solve_schedule(problem: list[FloatMeeting|FixedMeeting]):
  # problem = json.loads(problem)
  meetings_df = make_meetings_df(problem)

  result, schedule_df = kron_solver(meetings_df)
  # schedule = json.dumps(schedule)
  if result:
    return make_draft_ds(schedule_df)
  else:
    return None
