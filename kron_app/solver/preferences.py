

# User preferences: 
# for each user, extract their schedule (the set of meetings they might be in)
# then generate schedule features, such as contiguous meetings...


def get_schedule(user):


# measure schedule fragmentation




#schedule features:


#fragmentation: no gap between a floaty and the meeting before.
def nogaps(user_schedule):

  objective=constant(0)

  for meeting in meetings:
    if not meeting.is_fixed:
      #FIXME: we probably don't want to include the off-duty / on-duty-if-needed events as neighbors
      #  since that would result in trying to schedule meetings near them...
      #FIXME: can narrow this based on windows
      possible_prior_mtgs = meetings 

      #does closest meeting end when this one starts?
      any_right_before = ps.Or(ps.And(m.time.exist, meeting.time.start == m.time.end) for m in possible_prior_mtgs)

      objective = objective + ps.Ite(any_right_before, constant(1), constant(0))

  return objective


#fragmentation: how long before the last meeting?
#note that we probably don't want to include the off-duty / on-duty-if-needed events as neighbors
#  since that would result in trying to schedule meetings near them...
def nogaps(user_schedule):
  def relu(x):
    ps.max(0,x)

  objective = 0
  for user in users: 
    #get all the meetings they are (potentially) in:
    meetings = [m in allthemeetings if user in m.actualattendees] #FIXME use Set ops

    for meeting in meetings:
      if not meeting.is_fixed:
        possible_prior_mtgs = meetings #FIXME: can narrow this based on windows
        possible_next_mtgs = meetings

        #closest before meeting:
        dist_before = ps.min(relu(meeting.start-m.end) for m in possible_prior_mtgs)
        #closest after:
        dist_after = ps.min(relu(m.start-meeting.end) for m in possible_next_mtgs)

        #


#overlapping attendees in adjacent meetings.
def samepeople(user_schedule):
