import pytest
from datetime import datetime, timedelta
from kron_app import db
from kron_app.tests.helpers import mins, hrs, days, mkuser, mkevent_for_solver_tests as mkevent, isinit, isunscheduled, isscheduled, schedule, unschedule, mkclean, mkdirty, mkfinal, mkfixedevent, mkspace, mkconflict, setpriority, add_attendee, delete_attendee, mkavail
from kron_app.models import Series, User, Event, EventState
from kron_app.run_solver import run_solver, build_problem
from kron_app.events import build_weekly_series

# This implicitly does test db setup/teardown for all tests in this
# module. The alternative is to add the `testdb` fixture to individual
# tests as required.
@pytest.fixture(scope='function', autouse=True)
def autotestdb(testdb):
    pass

@pytest.fixture(scope='function')
def basetime():
    now = datetime.utcnow()
    #rounded to hour, two hours from now in order to not intersect freeze window:
    basetime = now.replace(second=0, microsecond=0, minute=0)+timedelta(hours=2)
    return basetime

def mkeventseries(creator, length, wstart, wlength, attendees, optionalattendees=[],repeats=2):
    theattendees = [dict(email=User.query.get(uid).email, optional=(uid in optionalattendees))
                         for uid in attendees+optionalattendees]
    event_data = dict(creator = creator,
                      length_in_mins = length.total_seconds()//60,
                      tzname = 'UTC',
                      window_start_local = wstart,
                      window_end_local = wstart+wlength,
                      freeze_horizon_in_days = 1,
                      title = "series..",
                      description = "",
                      location = '',
                      priority = None,
                      theattendees = theattendees)
    s=build_weekly_series(event_data,repeats)
    db.session.commit()
    return s

def test_no_events():
    assert Event.query.count() == 0
    tosync, emails = run_solver()
    assert tosync == []
    assert emails == []

def test_sat(utcnow):
    u = mkuser()
    mkavail(u, utcnow + days(1), days(1))
    e = mkevent(u, length=mins(30), wstart=utcnow, wlength=days(7), attendees=[u.id])
    assert isinit(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isscheduled(e)
    assert set(e.draft_attendees) == {u.id}
    assert tosync == [e.id]
    assert len(emails) == 0

def test_sat_unscheduled_to_scheduled(utcnow):
    u = mkuser()
    mkavail(u, utcnow + days(1), days(1))
    e = mkevent(u, length=mins(30), wstart=utcnow, wlength=days(7), attendees=[u.id])
    unschedule(e)
    assert isunscheduled(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isscheduled(e)
    assert set(e.draft_attendees) == {u.id}
    assert tosync == [e.id]
    assert len(emails) == 0

def test_schedule_highest_priority(utcnow,basetime):
    """test that if there are two events but only space for one of them, 
    the highest priority event is chosen, even if the other was already scheduled"""
    u1 = mkuser('n')
    u2 = mkuser('p')
    u3 = mkuser('e')
    e1 = mkevent(u1, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u2.id])
    e2 = mkevent(u3, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u3.id])
    schedule(e1, basetime, attendees=[u1.id, u2.id])
    assert isinit(e2)
    setpriority(e2, u1, 100)
    mkavail(u1, start_at=utcnow, length=hrs(12))
    mkavail(u2, start_at=utcnow, length=hrs(12))
    mkavail(u3, start_at=utcnow, length=hrs(12))
    tosync, emails = run_solver()
    assert isunscheduled(e1)
    assert isscheduled(e2)
    #now the user changes their priorities...
    setpriority(e2, u1, 10)
    setpriority(e1, u1, 100)
    mkdirty(e1)
    mkdirty(e2)
    tosync, emails = run_solver()
    assert isscheduled(e1)
    assert isunscheduled(e2)
 
def test_keep_draft_time(utcnow,basetime):
    """test that draft times are preserved, all else being equal"""
    u1 = mkuser('n')
    u2 = mkuser('p')
    e1 = mkevent(u1, length=hrs(1), wstart=basetime, wlength=hrs(2), attendees=[u1.id, u2.id])
    e2 = mkevent(u2, length=hrs(1), wstart=basetime, wlength=hrs(2), attendees=[u1.id, u2.id])
    schedule(e1, basetime, attendees=[u1.id, u2.id])
    schedule(e2, basetime+hrs(1), attendees=[u1.id, u2.id])
    # setpriority(e2, u1, 100)
    k1 = mkavail(u1, start_at=utcnow, length=hrs(12))
    k2 = mkavail(u2, start_at=utcnow, length=hrs(12))
    tosync, emails = run_solver()
    #check that events are at their original times
    assert e1.draft_start == basetime
    assert e2.draft_start == basetime+hrs(1)
    #now swap the draft times and check again that they are preserved
    schedule(e1, basetime+hrs(1), attendees=[u1.id, u2.id])
    schedule(e2, basetime, attendees=[u1.id, u2.id])
    tosync, emails = run_solver()
    assert e1.draft_start == basetime+hrs(1)
    assert e2.draft_start == basetime

def test_keep_scheduled(utcnow,basetime):
    """if there are two equal priority events, and only space for one of them, the scheduled event is chosen"""
    u1 = mkuser('n')
    u2 = mkuser('p')
    e1 = mkevent(u1, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u2.id])
    e2 = mkevent(u2, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u2.id])
    schedule(e2, basetime, attendees=[u1.id, u2.id])
    # setpriority(e2, u1, 100)
    k1 = mkavail(u1, start_at=utcnow, length=hrs(12))
    k2 = mkavail(u2, start_at=utcnow, length=hrs(12))
    # assert isscheduled(e2)
    tosync, emails = run_solver()
    #check that the schduled event is still scheduled
    assert isscheduled(e2)
    #check that the unscheduled event is unscheduled
    assert isunscheduled(e1)
    #now swap which is scheduled and check again
    schedule(e1, basetime, attendees=[u1.id, u2.id])
    unschedule(e2)
    tosync, emails = run_solver()
    assert isscheduled(e1)
    assert isunscheduled(e2)

def test_ignore_excitable_people(utcnow,basetime):
    """test that if one use assigns high priority to all events, 
    and another asigns mild priorities with some variance, 
    the latter will determine what is scheduled."""
    u1 = mkuser('n')
    u2 = mkuser('p')
    e1 = mkevent(u1, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u2.id])
    e2 = mkevent(u2, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u2.id])
    e3 = mkevent(u2, length=hrs(1), wstart=basetime+hrs(2), wlength=hrs(1), attendees=[u1.id, u2.id])
    e4 = mkevent(u1, length=hrs(1), wstart=basetime+hrs(4), wlength=hrs(1), attendees=[u1.id, u2.id])
    setpriority(e1, u1, 100)
    setpriority(e2, u1, 100)
    setpriority(e3, u1, 100)
    setpriority(e4, u1, 100)
    setpriority(e1, u2, 60)
    setpriority(e2, u2, 40)
    setpriority(e3, u2, 50)
    setpriority(e4, u2, 40)
    mkavail(u1, start_at=utcnow, length=hrs(12))
    mkavail(u2, start_at=utcnow, length=hrs(12))
    tosync, emails = run_solver()
    assert isscheduled(e1)
    assert isunscheduled(e2)

# TODO: the sat / unsat distinction here (in e.g. test names) doesn't
# make sense now. (all meetings are optional, so the problem is always
# sat.) rename tests?

def test_sat_init_to_unscheduled(utcnow):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=utcnow, wlength=days(1), attendees=[u.id])
    mkavail(u, utcnow + days(1), days(1))
    assert isinit(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isunscheduled(e)
    assert tosync == [e.id]
    assert len(emails) == 1

def test_sat_scheduled_to_unscheduled(utcnow):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=utcnow, wlength=days(1), attendees=[u.id])
    schedule(e, e.window_start+hrs(12), attendees=[u.id])
    mkavail(u, utcnow + days(1), days(1))
    assert isscheduled(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isunscheduled(e)
    assert tosync == [e.id]
    assert len(emails) == 1

def test_unsat_init_unschedule(utcnow):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=utcnow, wlength=hrs(12), attendees=[u.id])
    mkavail(u, utcnow + days(1), hrs(1))
    assert isinit(e)
    tosync, emails = run_solver()
    assert isunscheduled(e) 
    assert len(emails) == 1
    assert emails[0][0][0] == u.email
    assert tosync == [e.id]

def test_unsat_one_of_series(utcnow,basetime):
    u = mkuser()
    s = mkeventseries(u, length=mins(30), wstart=basetime, wlength=days(4), attendees=[u.id], repeats=3)
    f1 = mkfixedevent(u,start_at=basetime+days(6),length=days(7)) #==> second event in series skipped
    mkavail(u, start_at=basetime, length=days(22))
    tosync, emails = run_solver()
    #check that the conflicted element of series is skipped not extended:
    assert set(isscheduled(e) for e in s.events) == {True,True,False}
    assert len(emails) == 1

def test_unsat_scheduled_unschedule(utcnow):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=utcnow, wlength=days(1), attendees=[u.id])
    mkavail(u, utcnow+days(1), days(1))
    schedule(e, utcnow+hrs(12), attendees=e.attendees)
    assert isscheduled(e)
    tosync, emails = run_solver()
    assert isunscheduled(e)
    assert len(emails) == 1
    assert emails[0][0][0] == u.email
    assert tosync == [e.id]

def test_unsat_scheduled_new_conflict_unschedule(utcnow,basetime):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=basetime, wlength=days(1), attendees=[u.id])
    mkavail(u, basetime, days(2))
    schedule(e, basetime, attendees=e.attendees)
    assert isscheduled(e)
    mkclean(e)
    tosync, emails = run_solver()
    assert isscheduled(e)
    f = mkfixedevent(u,start_at=basetime,length=days(1))
    mkdirty(f)
    assert f.dirty
    tosync, emails = run_solver()
    assert isunscheduled(e)
    assert len(emails) == 1
    assert emails[0][0][0] == u.email
    assert tosync == [e.id]

def test_unsat_make_init_unscheduled(utcnow):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=utcnow+days(1), wlength=days(1), attendees=[u.id])
    mkavail(u, utcnow, hrs(12))
    assert isinit(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isunscheduled(e)
    assert len(emails) == 1
    assert emails[0][0][0] == u.email
    assert tosync == [e.id]

def test_unsat_make_scheduled_unscheduled(utcnow):
    u = mkuser()
    e = mkevent(u, length=mins(30), wstart=utcnow+days(1), wlength=days(1), attendees=[u.id])
    mkavail(u, utcnow, hrs(12))
    schedule(e, e.window_start, attendees=e.attendees)
    assert isscheduled(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isunscheduled(e)
    assert len(emails) == 1
    assert emails[0][0][0] == u.email
    print(emails)
    assert tosync == [e.id]

def test_unsat_make_init_unscheduled_nonoverlap_kronduty(utcnow):
    u1 = mkuser()
    u2 = mkuser('thedude@kron.com')
    e = mkevent(u1, length=mins(30), wstart=utcnow, wlength=days(2), attendees=[u1.id, u2.id])
    mkavail(u1, utcnow, hrs(12))
    mkavail(u2, utcnow+days(1), hrs(12))
    assert isinit(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isunscheduled(e)
    assert len(emails) == 1
    assert emails[0][0][0] == u1.email
    print(emails)
    assert tosync == [e.id]

def test_unsat_three_nonoverlap_kronduty(utcnow):
    u1 = mkuser('firefly@kron.com')
    u2 = mkuser('thedude@kron.com')
    u3 = mkuser('buffy@kron.com')
    e = mkevent(u1, length=mins(30), wstart=utcnow, wlength=days(2), attendees=[u1.id, u2.id, u3.id])
    mkavail(u1, utcnow, hrs(12))
    mkavail(u2, utcnow+hrs(10), hrs(12))
    mkavail(u3, utcnow+hrs(20), hrs(12))
    assert isinit(e)
    tosync, emails = run_solver()
    db.session.rollback()
    assert isunscheduled(e)
    assert len(emails) == 1
    assert emails[0][0][0] == u1.email
    print(emails)
    assert tosync == [e.id]

def test_earliest(utcnow,basetime):
    u1 = mkuser('n')
    e1 = mkevent(u1, length=hrs(2), wstart=basetime, wlength=hrs(4), attendees=[u1.id])
    mkavail(u1, start_at=utcnow, length=hrs(12))
    tosync, emails = run_solver()
    db.session.rollback()
    assert isscheduled(e1)
    print(f"  basetime {basetime}, e1: {e1.draft_start} -- {e1.draft_end}")
    assert e1.draft_start == basetime
    assert len(emails) == 0
    assert tosync == [e1.id]

def test_early_but_keep_optional(utcnow,basetime):
    u1 = mkuser('n')
    u2 = mkuser('p')
    u3 = mkuser('e')
    e1 = mkevent(u1, length=hrs(1), wstart=basetime, wlength=hrs(4), attendees=[u1.id, u2.id])
    e2 = mkevent(u3, length=hrs(1), wstart=basetime, wlength=hrs(1), attendees=[u1.id, u3.id])
    mkavail(u1, start_at=utcnow, length=hrs(12))
    mkavail(u2, start_at=utcnow, length=hrs(12))
    mkavail(u3, start_at=utcnow, length=hrs(12))
    tosync, emails = run_solver()
    db.session.rollback()
    assert isscheduled(e1)
    #e2 is optional, make sure it is scheduled, even though that means e1 isn't as early as possible:
    assert isscheduled(e2)
    print(f"  basetime {basetime}, e1: {e1.draft_start} -- {e1.draft_end}, e2: {e2.draft_start} -- {e2.draft_end}")
    #e1 is earliest it can be after e2:
    assert e1.draft_start == basetime+hrs(1)
    assert len(emails) == 0
    assert set(tosync) == {e1.id,e2.id}

def test_changes_to_non_conflicted_final_propagate(utcnow,basetime):
    u1 = mkuser('n')
    u2 = mkuser('p')
    u3 = mkuser('e')
    mkavail(u1, start_at=utcnow, length=hrs(12))
    mkavail(u2, start_at=utcnow, length=hrs(12))
    mkavail(u3, start_at=utcnow, length=hrs(12))
    e1 = mkevent(u1, length=mins(15), wstart=basetime, wlength=hrs(2), attendees=[u1.id], optionalattendees=[u2.id])
    schedule(e1,basetime,[u1.id,u2.id])
    mkfinal(e1)
    # Simulate editing an un-conflicted final event.
    e1.length = mins(30)
    add_attendee(e1, u3)
    delete_attendee(e1, u1)
    mkdirty(e1)
    assert e1.draft_end - e1.draft_start != e1.length
    assert set(e1.draft_attendees) == {u1.id,u2.id}
    tosync, _ = run_solver()
    assert tosync == [e1.id]
    assert e1.draft_end - e1.draft_start == e1.length
    assert set(e1.draft_attendees) == {u2.id,u3.id}

# `build_problem` tests

def mkdirtyfixedevent(user, start_at, end_at):
    return mkdirty(mkfixedevent(user, start_at, end_at-start_at))

def test_build_problem_basic_dirty_handling(basetime, utcnow):
    u = mkuser('p')
    e = mkevent(u, length=mins(20), wstart=basetime, wlength=hrs(1), attendees=[u.id])
    assert e.is_init()

    mkclean(e)
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()
    assert not e.dirty

    mkdirty(e)
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == {e}
    assert not e.dirty

    schedule(e, e.window_start, [u.id])
    assert e.is_scheduled()
    mkdirty(e)
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == {e}
    assert not e.dirty

    e.state = EventState.PENDING
    db.session.commit()
    assert e.is_pending()
    mkdirty(e) # Meaningless in this state, but more likely to catch bugs.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()

    e.state = EventState.FINALIZED
    db.session.commit()
    assert e.is_finalized()
    mkdirty(e) # Meaningless in this state, but more likely to catch bugs.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()

def test_build_problem_dirty_set_extended_with_overlapping_meetings(basetime, utcnow):
    u1 = mkuser('n')
    u2 = mkuser('p')
    u3 = mkuser('e')
    e1 = mkevent(u1, length=mins(15), wstart=basetime, wlength=hrs(2), attendees=[u1.id])
    e2 = mkevent(u1, length=mins(15), wstart=basetime+hrs(1), wlength=hrs(2), attendees=[u1.id], optionalattendees=[u2.id])
    # e3 doesn't overlap in time/users with e1, but does with e2.
    e3 = mkevent(u1, length=mins(15), wstart=basetime+hrs(2), wlength=hrs(2), attendees=[u2.id,u3.id])
    # No overlap in attendees
    e4 = mkevent(u1, length=mins(15), wstart=basetime+hrs(1), wlength=hrs(2), attendees=[])
    # No overlap in time.
    e5 = mkevent(u1, length=mins(15), wstart=basetime+hrs(4), wlength=hrs(2), attendees=[u2.id])
    mkdirty(e1)
    mkclean(e2)
    mkclean(e3)
    mkclean(e4)
    mkclean(e5)
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == {e1,e2,e3}
    # Nothing more to do.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()

@pytest.mark.parametrize('space_maker', [mkspace])
def test_build_problem_space_handling(basetime, utcnow, space_maker):
    u1 = mkuser('p')
    u2 = mkuser('n')
    e1 = mkevent(u1, length=mins(20), wstart=basetime, wlength=hrs(1), attendees=[u1.id])
    e2 = mkevent(u1, length=mins(20), wstart=basetime+hrs(1), wlength=hrs(1), attendees=[u1.id])
    schedule(e2, basetime+hrs(1), [u1.id])
    e3 = mkevent(u1, length=mins(20), wstart=basetime+hrs(2), wlength=hrs(1), attendees=[], optionalattendees=[u1.id])
    e4 = mkevent(u1, length=mins(20), wstart=basetime+hrs(3), wlength=hrs(1), attendees=[u2.id])
    e5 = mkevent(u1, length=mins(20), wstart=basetime+hrs(4), wlength=hrs(1), attendees=[u1.id,u2.id])
    e6 = mkevent(u1, length=mins(20), wstart=basetime+hrs(5), wlength=hrs(1), attendees=[u1.id])
    for e in [e1,e2,e3,e4,e5,e6]:
        mkclean(e)
    # None of these events are dirty.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()
    # They don't overlap (window or users), so don't interact, and can
    # therefore only be pulled into the problem by the space.
    for e in [e1,e2,e3,e4,e5,e6]:
        mkdirty(e)
        problemset, _, _, _ =  build_problem(utcnow)
        assert problemset == {e}
        mkclean(e)
    # Adding a space pulls meetings into problem set.
    s = space_maker(u1, start_at=basetime+mins(110), end_at=basetime+mins(250))
    problemset, _, _, _ =  build_problem(utcnow)
    # e1, e6 don't overlap the space in time
    # e4 doesn't overlap the space in (optional)attendees
    assert problemset == {e2,e3,e5}
    # Nothing more to do.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()

@pytest.mark.parametrize('conflict_maker', [mkconflict, mkdirtyfixedevent])
def test_build_problem_conflict_handling(basetime, utcnow, conflict_maker):
    u1 = mkuser('p')
    u2 = mkuser('n')
    e1 = mkevent(u1, length=mins(20), wstart=basetime, wlength=hrs(1), attendees=[u1.id])
    schedule(e1, e1.window_start+mins(20), [u1.id])
    e2 = mkevent(u1, length=mins(20), wstart=basetime+hrs(1), wlength=hrs(1), attendees=[u1.id])
    schedule(e2, e2.window_start+mins(20), [u1.id])
    e3 = mkevent(u1, length=mins(20), wstart=basetime+hrs(2), wlength=hrs(1), attendees=[u1.id,u2.id])
    schedule(e3, e3.window_start+mins(20), [u1.id])
    e4 = mkevent(u1, length=mins(20), wstart=basetime+hrs(3), wlength=hrs(1), attendees=[u1.id])
    e5 = mkevent(u1, length=mins(20), wstart=basetime+hrs(4), wlength=hrs(1), attendees=[u1.id,u2.id])
    schedule(e5, e5.window_start+mins(20), [u2.id])
    e6 = mkevent(u1, length=mins(20), wstart=basetime+hrs(5), wlength=hrs(1), attendees=[u1.id])
    schedule(e6, e6.window_start+mins(20), [u1.id])
    e7 = mkevent(u1, length=mins(20), wstart=basetime+hrs(6), wlength=hrs(1), attendees=[u2.id])
    schedule(e7, e7.window_start+mins(20), [u2.id])
    for e in [e1,e2,e3,e4,e5,e6,e7]:
        mkclean(e)
    # None of these are dirty.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()
    # They don't overlap (window or users), so don't interact, and can
    # therefore only be pulled into the problem by the conflict.
    for e in [e1,e2,e3,e4,e5,e6]:
        mkdirty(e)
        problemset, _, _, _ =  build_problem(utcnow)
        assert problemset == {e}
        mkclean(e)
    # Adding a conflict pulls meetings into the problem set.
    c = conflict_maker(u1, start_at=basetime+mins(90), end_at=basetime+mins(330))
    problemset, _, _, _ =  build_problem(utcnow)
    # e1, e7 don't overlap the conflict in time
    # e4 is not draft
    # e5 doesn't overlap the conflict in attendees
    assert problemset == {e2,e3,e6}
    # Nothing more to do.
    problemset, _, _, _ =  build_problem(utcnow)
    assert problemset == set()

def test_final(basetime,utcnow):
    """test when a final event can be in problem"""
    u1 = mkuser('n')
    u2 = mkuser('p')
    u3 = mkuser('e')
    mkavail(u1, start_at=utcnow, length=hrs(12))
    mkavail(u2, start_at=utcnow, length=hrs(12))
    mkavail(u3, start_at=utcnow, length=hrs(12))
    e1 = mkevent(u1, length=mins(15), wstart=basetime, wlength=hrs(2), attendees=[u1.id])
    schedule(e1,basetime,[u1.id])
    e2 = mkevent(u1, length=mins(15), wstart=basetime+hrs(1), wlength=hrs(2), attendees=[u1.id], optionalattendees=[u2.id])
    schedule(e2,basetime+hrs(1),[u1.id,u2.id])
    # e3 doesn't overlap in time/users with e1, but does with e2.
    e3 = mkevent(u1, length=mins(15), wstart=basetime+hrs(2), wlength=hrs(2), attendees=[u2.id,u3.id])
    schedule(e3,basetime+hrs(2),[u2.id,u3.id])
    # No overlap in attendees
    e4 = mkevent(u1, length=mins(15), wstart=basetime+hrs(1), wlength=hrs(2), attendees=[])
    schedule(e4,basetime+mins(15),[u1.id])
    # No overlap in time.
    e5 = mkevent(u1, length=mins(15), wstart=basetime+hrs(4), wlength=hrs(2), attendees=[u2.id])
    schedule(e5,basetime+hrs(4),[u1.id,u2.id])
    mkdirty(e1)
    mkclean(e2)
    mkclean(e3)
    mkfinal(e3)
    mkclean(e4)
    mkclean(e5)
    problemset, *_ =  build_problem(utcnow)
    assert problemset == {e1,e2} #e3 not included because final
    mkfinal(e1)
    mkdirty(e1)
    problemset, *_ =  build_problem(utcnow)
    assert problemset == set() #e1 dirty but final with no "real" conflicts
    mkclean(e1)
    mkdirtyfixedevent(u1,basetime,basetime+hrs(1))
    problemset, *_ =  build_problem(utcnow)
    assert problemset == {e1,e2,e4}#e1,e4 true conflicts, e2 not final pulled from e1.
    # Nothing more to do.
    problemset, *_ =  build_problem(utcnow)
    assert problemset == set()

def test_adjacent_windows(basetime,utcnow):
    """test that adjacent windows don't cause meeting interaction"""

    u = mkuser('p')
    mkavail(u, start_at=utcnow, length=hrs(12))
    e1 = mkevent(u, length=mins(15), wstart=basetime, wlength=hrs(1), attendees=[u.id])
    schedule(e1,basetime,[u.id])
    e2 = mkevent(u, length=mins(15), wstart=basetime+hrs(1), wlength=hrs(1), attendees=[u.id])
    schedule(e2,basetime+hrs(1),[u.id])
    assert e1.window_end == e2.window_start
    mkdirty(e1)
    mkclean(e2)
    problemset, *_ = build_problem(utcnow) #Note: default builds out big enough problem..
    assert problemset == {e1}
    mkclean(e1)
    mkdirty(e2)
    problemset, *_ = build_problem(utcnow)
    assert problemset == {e2}

def test_problem_limits(basetime,utcnow):
    """test that build problem with size and iteration limits works"""
    u1 = mkuser('p')
    u2 = mkuser('n')
    e1 = mkevent(u1, length=mins(30), wstart=basetime, wlength=hrs(2), attendees=[u1.id,u2.id])
    for i in range(1,10):
        e=mkevent(u2, length=mins(30), wstart=basetime+hrs(i), wlength=hrs(2), attendees=[u2.id])
        mkclean(e)
    mkdirty(e1)
    problemset, *_ = build_problem(utcnow)
    assert len(problemset)==10
    mkdirty(e1)
    problemset, *_ = build_problem(utcnow, max_size=5)
    assert len(problemset)==5
    mkdirty(e1)
    problemset, *_ = build_problem(utcnow, max_iterations=5)
    assert len(problemset)==6
    mkdirty(e1)
    problemset, *_ = build_problem(utcnow, max_size=5, min_iterations=6)
    assert len(problemset)==7


# def test_extend_windows3():
#   floaties=[FloatMeeting(id='11', attendees=['1'], optionalattendees=[], window_start=d(2022, 4, 1, 6, 0), window_end=d(2022, 4, 1, 8, 0), length=td(minutes=30), priority=None, is_optional=False, is_fixed=False)]
#   fixies=[
#   FixedMeeting(attendees=['1'], id='56', start=d(2022, 4, 1, 2, 0), length=td(hours=9), priority=None, is_optional=False, is_fixed=True), 
#   FixedMeeting(attendees=['1'], id='offduty1', start=d(2022, 3, 30, 0, 0), length=td(hours=8), priority=None, is_optional=False, is_fixed=True), 
#   FixedMeeting(attendees=['1'], id='offduty2', start=d(2022, 3, 30, 16, 0), length=td(hours=16), priority=None, is_optional=False, is_fixed=True), 
#   FixedMeeting(attendees=['1'], id='offduty3', start=d(2022, 3, 31, 16, 0), length=td(hours=16), priority=None, is_optional=False, is_fixed=True)
#   ]
#   now=d(2022, 4, 1, 5, 0)
#   extensions = extend_windows(floaties,fixies, ["11"],now)
#   print(extensions)
#   assert(extensions=={'11': td(minutes=210)})
