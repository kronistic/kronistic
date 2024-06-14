import pytest
from kron_app import db
from kron_app.groups import unpack_groups, get_deps, group_add, group_update, group_delete
from kron_app.models import Change
from kron_app.tests.helpers import mkuser, hrs

@pytest.mark.parametrize('nick, groups, expected', [
    ('g', {}, set()),
    ('g', {'h':['u@k']}, set()),
    ('g', {'g':['u@k','v@k']}, {'u@k','v@k'}),
    ('g', {'g':['h'], 'h':['u@k','v@k']}, {'u@k','v@k'}),
    ('g', {'g':['h','w@k'], 'h':['u@k','v@k']}, {'w@k','u@k','v@k'}),
    ('h', {'g':['h','w@k'], 'h':['u@k','v@k']}, {'u@k','v@k'}),
    ('g', {'g': ['h'], 'h': ['g']}, set()),
    ('g', {'g': ['h', 'w@k'], 'h': ['g', 'u@k']}, {'w@k','u@k'}),
    ('g', {'g': ['g','w@k']}, {'w@k'}),
    ('g', {'g': ['h','u@k'], 'h': ['g','u@k']}, {'u@k'}),
    ('gG', {'Gg': ['hH'], 'Hh': ['u@k']}, {'u@k'}),
])
def test_unpack_groups(nick, groups, expected):
    assert unpack_groups(nick, groups) == expected

@pytest.mark.parametrize('groups, nick, members, expected', [
    ({}, 'g', [], {'g': []}),
    ({}, 'g', ['u@k'], {'g': ['u@k']}),
    ({'g': ['u@k']}, 'h', ['g','v@k'], {'g': ['u@k'], 'h': ['g','v@k']}),
    ({}, 'g', ['g'], {'g': ['g']}),
])
def test_group_add(groups, nick, members, expected):
    assert group_add(groups, nick, members) == expected

@pytest.mark.parametrize('groups, nick, newnick, members, expected', [
    ({'g': []}, 'g', 'g', ['u@k'], {'g': ['u@k']}),
    ({'g': ['u@k']}, 'g', 'g', ['u@k'], {'g': ['u@k']}),
    ({'g': ['u@k']}, 'g', 'g', ['v@k'], {'g': ['v@k']}),
    ({'g': ['u@k']}, 'g', 'g', ['u@k','v@k'], {'g': ['u@k','v@k']}),
    ({'g': ['u@k']}, 'g', 'g', [], {'g': []}),
    ({'g': []}, 'g', 'h', [], {'h': []}),
    ({'g': ['u@k']}, 'g', 'h', ['v@k'], {'h': ['v@k']}),
    ({'g': ['u@k']}, 'g', 'h', ['u@k','v@k'], {'h': ['u@k','v@k']}),
    ({'g': [], 'h': ['g'], 'i': ['h']}, 'g', 'g2', [], {'g2': [], 'h': ['g2'], 'i': ['h']}),
    ({'g': ['u@k'], 'h': ['g','v@k'], 'i': ['h','w@k']}, 'g', 'g2', ['u2@k'], {'g2': ['u2@k'], 'h': ['g2','v@k'], 'i': ['h','w@k']}),
    ({'g': []}, 'g', 'g', ['g'], {'g': ['g']}),
    ({'g': ['g']}, 'g', 'g2', ['g'], {'g2': ['g2']}),
])
def test_group_update(groups, nick, newnick, members, expected):
    assert group_update(groups, nick, newnick, members) == expected

@pytest.mark.parametrize('groups, nick, expected', [
    ({'g': ['u@k']}, 'g', {}),
    ({'g': [], 'h': ['g', 'u@k']}, 'g', {'h': ['u@k']}),
])
def test_group_delete(groups, nick, expected):
    assert group_delete(groups, nick) == expected

@pytest.mark.parametrize('nick, groups, expected', [
    ('g', {}, {'g'}),
    ('g', {'g': [], 'h': ['g']}, {'g','h'}),
    ('g', {'g': [], 'h': ['g','j'], 'i': ['h'], 'j': ['k'], 'k': []}, {'g','h','i'}),
    ('g', {'g': ['h'], 'h': ['g']}, {'g','h'}),
    ('g', {'g': ['h'], 'h': ['i'], 'i': ['g']}, {'g','h','i'}),
])
def test_get_deps(nick, groups, expected):
    assert get_deps(nick, groups) == expected
