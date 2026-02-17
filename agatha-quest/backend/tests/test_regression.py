"""
Regression pack: critical gameplay flows for Agatha Quest.

Covers: investigation, pressure clock, map travel (locations),
clue board, accusation, and failure paths.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, reset_game, sessions
from game_data import SUSPECTS, CLUES, LOCATIONS, CASE_INFO, PRESSURE_CLOCK


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        reset_game()
        c.post('/api/game/new')  # Establish a session
        yield c


# ── Critical path: win via location exploration ──

def test_regression_win_via_locations(client):
    """Full win path using location-based exploration."""
    # New game
    r = client.post('/api/game/new')
    assert r.status_code == 200
    case = r.get_json()['case_info']
    assert case['victim'] == 'Lord Reginald Blackwood'

    # Explore rooms and find clues
    r = client.post('/api/game/locations/study/search')
    assert r.status_code == 200
    assert len(r.get_json()['clues_found']) == 1

    r = client.post('/api/game/locations/victim_room/search')
    assert r.status_code == 200
    assert len(r.get_json()['clues_found']) == 1

    # Interrogate two suspects
    r = client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
    assert r.status_code == 200
    assert r.get_json()['interrogation']['secret_revealed'] is True

    r = client.post('/api/game/interrogate', json={'suspect_id': 'butler_james'})
    assert r.status_code == 200

    # State should be accusation phase
    r = client.get('/api/game/state')
    state = r.get_json()
    assert state['phase'] == 'accusation'
    assert state['clues_discovered_count'] == 2
    assert state['locations_visited_count'] == 2
    assert state['interrogations_count'] == 2

    # Accuse correct culprit
    r = client.post('/api/game/accuse', json={'suspect_id': 'dr_hartley'})
    data = r.get_json()
    assert data['correct'] is True
    assert data['status'] == 'success'

    # Game over
    r = client.get('/api/game/state')
    assert r.get_json()['phase'] == 'complete'
    assert r.get_json()['game_won'] is True


# ── Critical path: win via direct clue discovery ──

def test_regression_win_via_direct_clues(client):
    """Full win path using direct clue discovery endpoint."""
    client.post('/api/game/new')

    client.post('/api/game/clues/poison_vial/discover')
    client.post('/api/game/clues/torn_letter/discover')
    client.post('/api/game/interrogate', json={'suspect_id': 'dr_hartley'})
    client.post('/api/game/interrogate', json={'suspect_id': 'miss_winters'})

    r = client.get('/api/game/state')
    assert r.get_json()['phase'] == 'accusation'

    r = client.post('/api/game/accuse', json={'suspect_id': 'dr_hartley'})
    assert r.get_json()['correct'] is True


# ── Critical path: wrong accusation ──

def test_regression_wrong_accusation(client):
    """Full game ending in wrong accusation."""
    client.post('/api/game/new')
    client.post('/api/game/clues/poison_vial/discover')
    client.post('/api/game/clues/torn_letter/discover')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
    client.post('/api/game/interrogate', json={'suspect_id': 'butler_james'})

    r = client.post('/api/game/accuse', json={'suspect_id': 'lady_blackwood'})
    data = r.get_json()
    assert data['correct'] is False
    assert data['culprit'] == 'dr_hartley'

    r = client.get('/api/game/state')
    assert r.get_json()['game_won'] is False


# ── Critical path: pressure clock timeout ──

def test_regression_pressure_timeout_during_investigation(client):
    """Game ends when pressure clock runs out mid-investigation."""
    client.post('/api/game/new')

    # Burn pressure: 6 searches (cost 1 each) + 2 interrogations (cost 2 each) = 10
    client.post('/api/game/locations/study/search')       # 9 remaining
    client.post('/api/game/locations/victim_room/search')  # 8
    client.post('/api/game/locations/hallway/search')       # 7
    client.post('/api/game/locations/victim_desk/search')   # 6
    client.post('/api/game/locations/garden/search')        # 5
    client.post('/api/game/locations/pantry/search')        # 4

    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})  # 2

    # This interrogation should exhaust remaining pressure (2 - 2 = 0)
    r = client.post('/api/game/interrogate', json={'suspect_id': 'dr_hartley'})
    data = r.get_json()
    assert data['status'] == 'failure'
    assert data['pressure_remaining'] == 0

    # Game over
    r = client.get('/api/game/state')
    state = r.get_json()
    assert state['phase'] == 'complete'
    assert state['game_won'] is False


# ── Critical path: pressure warning triggers correctly ──

def test_regression_pressure_warning_at_threshold(client):
    """Pressure warning appears when remaining hits threshold."""
    client.post('/api/game/new')

    # Spend down to warning zone: initial=10, warning=3
    # 4 searches (cost 1) + 1 interrogation (cost 2) = 6 spent, 4 remaining
    client.post('/api/game/locations/study/search')
    client.post('/api/game/locations/victim_room/search')
    client.post('/api/game/locations/hallway/search')
    client.post('/api/game/locations/victim_desk/search')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})

    # State should show 4 remaining, no warning yet
    r = client.get('/api/game/state')
    assert r.get_json()['pressure_remaining'] == 4
    assert r.get_json()['pressure_warning'] is False

    # Next search brings to 3 (warning threshold)
    r = client.post('/api/game/locations/garden/search')
    data = r.get_json()
    assert data['pressure_remaining'] == 3
    assert 'pressure_warning' in data

    r = client.get('/api/game/state')
    assert r.get_json()['pressure_warning'] is True


# ── Map travel: all locations accessible and correct clue mapping ──

def test_regression_all_locations_clue_mapping(client):
    """Every location is searchable and maps to correct clues."""
    expected = {
        'study': ['poison_vial'],
        'victim_room': ['torn_letter'],
        'hallway': ['muddy_footprints'],
        'victim_desk': ['blackmail_note'],
        'garden': [],
        'pantry': [],
    }

    r = client.get('/api/game/locations')
    locs = r.get_json()['locations']
    assert len(locs) == 6

    for loc_id, expected_clues in expected.items():
        r = client.post(f'/api/game/locations/{loc_id}/search')
        assert r.status_code == 200
        found = [c['id'] for c in r.get_json()['clues_found']]
        assert sorted(found) == sorted(expected_clues), f"Mismatch at {loc_id}"


# ── Clue board: all clues discoverable and tracked ──

def test_regression_all_clues_discoverable(client):
    """All 4 clues can be discovered and appear on the clue board."""
    for clue in CLUES:
        r = client.post(f'/api/game/clues/{clue["id"]}/discover')
        assert r.status_code == 200

    r = client.get('/api/game/clues')
    data = r.get_json()
    assert data['discovered_count'] == 4
    assert data['total_clues'] == 4
    ids = [c['id'] for c in data['clues']]
    for clue in CLUES:
        assert clue['id'] in ids


# ── Investigation: interrogation records ──

def test_regression_interrogation_records(client):
    """All suspects can be interrogated and records are retrievable."""
    for s in SUSPECTS:
        r = client.post('/api/game/interrogate', json={'suspect_id': s['id']})
        assert r.status_code == 200

    r = client.get('/api/game/interrogations')
    data = r.get_json()
    assert len(data['interrogations']) == 4
    ids = [i['suspect_id'] for i in data['interrogations']]
    for s in SUSPECTS:
        assert s['id'] in ids


# ── Edge case: new game fully resets everything ──

def test_regression_new_game_full_reset(client):
    """New game resets all state including pressure and locations."""
    # Play partially
    client.post('/api/game/locations/study/search')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})

    # Reset
    client.post('/api/game/new')

    r = client.get('/api/game/state')
    state = r.get_json()
    assert state['phase'] == 'investigation'
    assert state['clues_discovered_count'] == 0
    assert state['locations_visited_count'] == 0
    assert state['interrogations_count'] == 0
    assert state['pressure_remaining'] == PRESSURE_CLOCK['initial']
    assert state['game_won'] is None

    # Locations should show unvisited
    r = client.get('/api/game/locations')
    for loc in r.get_json()['locations']:
        assert loc['visited'] is False

    # Clues should be empty
    r = client.get('/api/game/clues')
    assert r.get_json()['discovered_count'] == 0


# ── Edge case: blocked actions after game over ──

def test_regression_all_actions_blocked_after_game_over(client):
    """After game completion, all investigation actions are blocked."""
    # Win the game
    client.post('/api/game/clues/poison_vial/discover')
    client.post('/api/game/clues/torn_letter/discover')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
    client.post('/api/game/interrogate', json={'suspect_id': 'dr_hartley'})
    client.post('/api/game/accuse', json={'suspect_id': 'dr_hartley'})

    # All actions should fail
    r = client.post('/api/game/locations/garden/search')
    assert r.status_code == 400

    r = client.post('/api/game/interrogate', json={'suspect_id': 'butler_james'})
    assert r.status_code == 400

    r = client.post('/api/game/accuse', json={'suspect_id': 'lady_blackwood'})
    assert r.status_code == 400


# ── Edge case: secrets only revealed with enough clues ──

def test_regression_secret_reveal_gate(client):
    """Secrets are hidden with <2 clues and revealed with >=2 clues."""
    # With 0 clues: no secret
    r = client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
    assert r.get_json()['interrogation']['secret_revealed'] is False

    # With 1 clue: still no secret
    client.post('/api/game/clues/poison_vial/discover')
    r = client.post('/api/game/interrogate', json={'suspect_id': 'butler_james'})
    assert r.get_json()['interrogation']['secret_revealed'] is False

    # With 2 clues: secret revealed
    client.post('/api/game/clues/torn_letter/discover')
    r = client.post('/api/game/interrogate', json={'suspect_id': 'dr_hartley'})
    interrog = r.get_json()['interrogation']
    assert interrog['secret_revealed'] is True
    assert 'secret' in interrog
