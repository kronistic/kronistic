"""NOTE: the work previously done by on_to_off_duty is now done by PWfns.."""

from uuid import uuid4
from datetime import datetime,timedelta
from kron_app import db
from kron_app.tests.helpers import mkuser
from kron_app.models import User, Calendar
from kron_app.run_solver import on_to_off_duty, split_times, prefs_to_onduty

def test1():
	"""test when on_duty" is in the middle of window"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=1), 'length': timedelta(hours=4)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now, now+timedelta(hours=6))

	print("off_duty: ", off_duty)

	assert(len(off_duty)==2)
	assert(off_duty ==
		[{'start':now, 'length':timedelta(hours=1)},
		 {'start':now+timedelta(hours=5), 'length': timedelta(hours=1)}])

def test2():
	"""test when on_duty starts before window"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now, 'length': timedelta(hours=4)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now+timedelta(hours=1), now+timedelta(hours=6))

	print("off_duty: ", off_duty)

	assert(len(off_duty)==1)
	assert(off_duty==
		[{'start':now+timedelta(hours=4), 'length':timedelta(hours=2)}])

def test3():
	"""test when on_duty overlaps end of window"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=4), 'length': timedelta(hours=4)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now, now+timedelta(hours=6))

	print("off_duty: ", off_duty)

	assert(len(off_duty)==1)
	assert(off_duty==
		[{'start':now, 'length':timedelta(hours=4)}])

def test4():
	"""test when two on_duty events overlap"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=2), 'length': timedelta(hours=2)},
				{'start': now+timedelta(hours=3), 'length': timedelta(hours=1)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now, now+timedelta(hours=6))

	print("off_duty: ", off_duty)
	print([((t['start']-now).total_seconds()//(60*60), (t['start']+t['length']-now).total_seconds()//(60*60)) for t in off_duty])

	assert(len(off_duty)==2)
	# assert(off_duty==
	# 	[{'start':now, 'length':timedelta(hours=4)}])

def test5():
	"""test when two on_duty events overlap a different way"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=2), 'length': timedelta(hours=2)},
				{'start': now+timedelta(hours=3), 'length': timedelta(hours=2)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now, now+timedelta(hours=6))

	print("off_duty: ", off_duty)
	print([((t['start']-now).total_seconds()//(60*60), (t['start']+t['length']-now).total_seconds()//(60*60)) for t in off_duty])

	assert(len(off_duty)==2)
	# assert(off_duty==
	# 	[{'start':now, 'length':timedelta(hours=4)}])

def test6():
	"""three overlap"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=1), 'length': timedelta(hours=4)},
				{'start': now+timedelta(hours=2), 'length': timedelta(hours=2)},
				{'start': now+timedelta(hours=3), 'length': timedelta(hours=2)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now, now+timedelta(hours=6))

	print("off_duty: ", off_duty)
	print([((t['start']-now).total_seconds()//(60*60), (t['start']+t['length']-now).total_seconds()//(60*60)) for t in off_duty])

	assert(len(off_duty)==2)
	# assert(off_duty==
	# 	[{'start':now, 'length':timedelta(hours=4)}])


def test7():
	"""test several on_duty events not all have overlaps"""
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=1), 'length': timedelta(hours=1)},
				{'start': now+timedelta(hours=3), 'length': timedelta(hours=2)},
				{'start': now+timedelta(hours=4), 'length': timedelta(hours=2)}]
	print("on duty: ", on_duty)

	off_duty = on_to_off_duty(on_duty,now, now+timedelta(hours=6))

	print("off_duty: ", off_duty)
	print([((t['start']-now).total_seconds()//(60*60), (t['start']+t['length']-now).total_seconds()//(60*60)) for t in off_duty])

	assert(len(off_duty)==2)
	# assert(off_duty==
	# 	[{'start':now, 'length':timedelta(hours=4)}])

def test_split_times():
	now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
	on_duty = [{'start': now+timedelta(hours=0), 'length': timedelta(minutes=150), 'is_optional': True, 'priority': 1},
				{'start': now+timedelta(hours=3), 'length': timedelta(hours=2), 'is_optional': True, 'priority': 1}]
	on_duty = split_times(on_duty,timedelta(minutes=60))
	print("on duty: ", on_duty)
	assert(len(on_duty)==5)

def test_prefs_to_onduty(testdb):
    u = mkuser()
    u.tzname = 'Europe/London'
    db.session.commit()
    times = prefs_to_onduty(u.id, datetime(2022,10,28), datetime(2022,11,1))
    assert len(times) == 3
    assert times[0]['start'] == datetime(2022,10,27,8)
    assert times[1]['start'] == datetime(2022,10,28,8)
    assert times[2]['start'] == datetime(2022,10,31,9) # DST - clocks back 1hr Oct 30 2022
