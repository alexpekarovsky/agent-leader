"""
Test suite for Agatha Quest backend API.
"""
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, reset_game, sessions
from game_data import SUSPECTS, CLUES, LOCATIONS, CASE_INFO, PRESSURE_CLOCK


def get_session_state(client):
    """Get the game state dict for the test client's current session."""
    cookie = client.get_cookie('agatha_session')
    if cookie:
        return sessions.get(cookie.value)
    return None


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        reset_game()  # Clear all sessions
        client.post('/api/game/new')  # Establish a session
        yield client


def unlock_accusation_phase(client):
    """Helper to unlock accusation phase by meeting evidence requirements."""
    # Discover 2 clues
    client.post(f'/api/game/clues/{CLUES[0]["id"]}/discover')
    client.post(f'/api/game/clues/{CLUES[1]["id"]}/discover')
    # Interrogate 2 suspects
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[1]['id']})


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'
    assert data['service'] == 'agatha-quest-backend'


def test_new_game(client):
    """Test starting a new game."""
    response = client.post('/api/game/new')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert 'case_info' in data
    assert data['case_info']['victim'] == CASE_INFO['victim']


def test_get_state_initial(client):
    """Test getting initial game state."""
    response = client.get('/api/game/state')
    assert response.status_code == 200
    data = response.get_json()
    assert data['phase'] == 'investigation'
    assert data['clues_discovered_count'] == 0
    assert data['locations_visited_count'] == 0
    assert data['interrogations_count'] == 0
    assert data['final_accusation'] is None
    assert data['game_won'] is None


def test_get_suspects(client):
    """Test getting list of suspects."""
    response = client.get('/api/game/suspects')
    assert response.status_code == 200
    data = response.get_json()
    assert 'suspects' in data
    assert len(data['suspects']) == len(SUSPECTS)

    # Check that secrets are not exposed
    for suspect in data['suspects']:
        assert 'secret' not in suspect
        assert 'id' in suspect
        assert 'name' in suspect
        assert 'description' in suspect


def test_get_clues_empty(client):
    """Test getting clues when none discovered."""
    response = client.get('/api/game/clues')
    assert response.status_code == 200
    data = response.get_json()
    assert data['discovered_count'] == 0
    assert data['total_clues'] == len(CLUES)
    assert len(data['clues']) == 0


def test_discover_clue(client):
    """Test discovering a clue."""
    clue_id = CLUES[0]['id']
    response = client.post(f'/api/game/clues/{clue_id}/discover')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['clue']['id'] == clue_id

    # Verify it appears in clues list
    response = client.get('/api/game/clues')
    data = response.get_json()
    assert data['discovered_count'] == 1


def test_discover_clue_twice(client):
    """Test that discovering same clue twice fails."""
    clue_id = CLUES[0]['id']

    # First discovery
    response = client.post(f'/api/game/clues/{clue_id}/discover')
    assert response.status_code == 200

    # Second attempt
    response = client.post(f'/api/game/clues/{clue_id}/discover')
    assert response.status_code == 400
    data = response.get_json()
    assert data['status'] == 'error'


def test_discover_invalid_clue(client):
    """Test discovering non-existent clue."""
    response = client.post('/api/game/clues/fake_clue/discover')
    assert response.status_code == 404


def test_interrogate_suspect(client):
    """Test interrogating a suspect."""
    suspect_id = SUSPECTS[0]['id']
    response = client.post('/api/game/interrogate', json={'suspect_id': suspect_id})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['interrogation']['suspect_id'] == suspect_id
    assert 'alibi' in data['interrogation']


def test_interrogate_reveals_secret_with_clues(client):
    """Test that interrogation reveals secrets when clues are found."""
    # Discover 2 clues first
    client.post(f'/api/game/clues/{CLUES[0]["id"]}/discover')
    client.post(f'/api/game/clues/{CLUES[1]["id"]}/discover')

    # Interrogate
    suspect_id = SUSPECTS[0]['id']
    response = client.post('/api/game/interrogate', json={'suspect_id': suspect_id})
    data = response.get_json()
    assert data['interrogation']['secret_revealed'] is True
    assert 'secret' in data['interrogation']


def test_interrogate_no_secret_without_clues(client):
    """Test that interrogation doesn't reveal secrets without enough clues."""
    suspect_id = SUSPECTS[0]['id']
    response = client.post('/api/game/interrogate', json={'suspect_id': suspect_id})
    data = response.get_json()
    assert data['interrogation']['secret_revealed'] is False
    assert 'secret' not in data['interrogation']


def test_interrogate_twice_fails(client):
    """Test that interrogating same suspect twice fails."""
    suspect_id = SUSPECTS[0]['id']

    # First interrogation
    response = client.post('/api/game/interrogate', json={'suspect_id': suspect_id})
    assert response.status_code == 200

    # Second attempt
    response = client.post('/api/game/interrogate', json={'suspect_id': suspect_id})
    assert response.status_code == 400


def test_interrogate_missing_suspect_id(client):
    """Test interrogation with missing suspect_id."""
    response = client.post('/api/game/interrogate', json={})
    assert response.status_code == 400


def test_interrogate_invalid_json_body(client):
    """Test interrogation with invalid JSON body."""
    response = client.post(
        '/api/game/interrogate',
        data='not-json',
        content_type='application/json',
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data['status'] == 'error'


def test_interrogate_invalid_suspect(client):
    """Test interrogating non-existent suspect."""
    response = client.post('/api/game/interrogate', json={'suspect_id': 'fake_suspect'})
    assert response.status_code == 404


def test_accuse_correct_culprit(client):
    """Test making correct accusation."""
    unlock_accusation_phase(client)  # Meet evidence requirements
    culprit_id = CASE_INFO['culprit']
    response = client.post('/api/game/accuse', json={'suspect_id': culprit_id})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['correct'] is True

    # Verify game state updated
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'complete'
    assert data['game_won'] is True


def test_accuse_wrong_culprit(client):
    """Test making wrong accusation."""
    unlock_accusation_phase(client)  # Meet evidence requirements
    # Pick someone who isn't the culprit
    wrong_suspect = next(s['id'] for s in SUSPECTS if s['id'] != CASE_INFO['culprit'])

    response = client.post('/api/game/accuse', json={'suspect_id': wrong_suspect})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['correct'] is False
    assert data['culprit'] == CASE_INFO['culprit']

    # Verify game state
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'complete'
    assert data['game_won'] is False


def test_accuse_without_enough_evidence(client):
    """Test that accusation is blocked without enough evidence."""
    culprit_id = CASE_INFO['culprit']
    response = client.post('/api/game/accuse', json={'suspect_id': culprit_id})
    assert response.status_code == 400
    data = response.get_json()
    assert 'evidence' in data['message'].lower()


def test_accuse_missing_suspect_id(client):
    """Test accusation with missing suspect_id."""
    response = client.post('/api/game/accuse', json={})
    assert response.status_code == 400


def test_accuse_invalid_json_body(client):
    """Test accusation with invalid JSON body."""
    response = client.post(
        '/api/game/accuse',
        data='not-json',
        content_type='application/json',
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data['status'] == 'error'


def test_accuse_invalid_suspect(client):
    """Test accusing non-existent suspect."""
    unlock_accusation_phase(client)  # Meet evidence requirements
    response = client.post('/api/game/accuse', json={'suspect_id': 'fake_suspect'})
    assert response.status_code == 404


def test_accuse_twice_fails(client):
    """Test that can't accuse after game is complete."""
    unlock_accusation_phase(client)  # Meet evidence requirements
    # First accusation
    response = client.post('/api/game/accuse', json={'suspect_id': CASE_INFO['culprit']})
    assert response.status_code == 200

    # Second attempt
    response = client.post('/api/game/accuse', json={'suspect_id': SUSPECTS[0]['id']})
    assert response.status_code == 400


def test_full_game_flow(client):
    """Test complete game workflow."""
    # 1. Start new game
    response = client.post('/api/game/new')
    assert response.status_code == 200

    # 2. Get suspects
    response = client.get('/api/game/suspects')
    assert response.status_code == 200

    # 3. Discover clues
    client.post(f'/api/game/clues/{CLUES[0]["id"]}/discover')
    client.post(f'/api/game/clues/{CLUES[1]["id"]}/discover')

    # 4. Interrogate suspects
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[1]['id']})

    # 5. Make accusation
    response = client.post('/api/game/accuse', json={'suspect_id': CASE_INFO['culprit']})
    data = response.get_json()
    assert data['correct'] is True

    # 6. Verify final state
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'complete'
    assert data['game_won'] is True
    assert data['clues_discovered_count'] == 2
    assert data['interrogations_count'] == 2


# --- Location exploration tests ---

def test_get_locations(client):
    """Test listing all locations."""
    response = client.get('/api/game/locations')
    assert response.status_code == 200
    data = response.get_json()
    assert 'locations' in data
    assert len(data['locations']) == len(LOCATIONS)
    for loc in data['locations']:
        assert 'id' in loc
        assert 'name' in loc
        assert 'description' in loc
        assert 'visited' in loc
        assert 'has_clues' in loc


def test_get_location_detail(client):
    """Test getting a specific location."""
    response = client.get('/api/game/locations/study')
    assert response.status_code == 200
    data = response.get_json()
    assert data['id'] == 'study'
    assert data['name'] == 'The Study'
    assert data['visited'] is False
    assert data['clues_found'] == []


def test_get_location_not_found(client):
    """Test getting non-existent location."""
    response = client.get('/api/game/locations/fake_room')
    assert response.status_code == 404


def test_search_location_finds_clue(client):
    """Test searching a location discovers its clues."""
    response = client.post('/api/game/locations/study/search')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert len(data['clues_found']) == 1
    assert data['clues_found'][0]['id'] == 'poison_vial'

    # Verify clue now appears in discovered clues
    response = client.get('/api/game/clues')
    assert response.get_json()['discovered_count'] == 1


def test_search_location_no_clues(client):
    """Test searching a location with no clues."""
    response = client.post('/api/game/locations/garden/search')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert len(data['clues_found']) == 0
    assert 'nothing new' in data['message'].lower()


def test_search_location_marks_visited(client):
    """Test that searching marks location as visited."""
    client.post('/api/game/locations/study/search')

    response = client.get('/api/game/locations/study')
    data = response.get_json()
    assert data['visited'] is True

    # Verify in state
    response = client.get('/api/game/state')
    assert response.get_json()['locations_visited_count'] == 1


def test_search_location_twice_no_duplicate_clues(client):
    """Test searching same location twice doesn't duplicate clues."""
    client.post('/api/game/locations/study/search')
    response = client.post('/api/game/locations/study/search')
    data = response.get_json()
    assert len(data['clues_found']) == 0  # Already found

    # Still only 1 clue discovered total
    response = client.get('/api/game/clues')
    assert response.get_json()['discovered_count'] == 1


def test_search_location_not_found(client):
    """Test searching non-existent location."""
    response = client.post('/api/game/locations/fake_room/search')
    assert response.status_code == 404


def test_location_search_unlocks_accusation(client):
    """Test that discovering clues via location search unlocks accusation."""
    # Search two locations with clues
    client.post('/api/game/locations/study/search')
    client.post('/api/game/locations/victim_room/search')
    # Interrogate 2 suspects
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[1]['id']})

    # Should be in accusation phase now
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'accusation'


def test_location_detail_shows_found_clues(client):
    """Test that location detail shows clues found there."""
    client.post('/api/game/locations/study/search')

    response = client.get('/api/game/locations/study')
    data = response.get_json()
    assert len(data['clues_found']) == 1
    assert data['clues_found'][0]['id'] == 'poison_vial'


def test_full_game_flow_with_locations(client):
    """Test complete game using location exploration."""
    # Start new game
    client.post('/api/game/new')

    # Explore locations
    client.post('/api/game/locations/study/search')
    client.post('/api/game/locations/victim_room/search')
    client.post('/api/game/locations/garden/search')

    # Interrogate suspects
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
    client.post('/api/game/interrogate', json={'suspect_id': 'dr_hartley'})

    # Verify state
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'accusation'
    assert data['locations_visited_count'] == 3
    assert data['clues_discovered_count'] == 2

    # Make correct accusation
    response = client.post('/api/game/accuse', json={'suspect_id': 'dr_hartley'})
    data = response.get_json()
    assert data['correct'] is True


# --- Pressure clock tests ---

def test_pressure_in_initial_state(client):
    """Test that initial state includes pressure clock."""
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['pressure_remaining'] == PRESSURE_CLOCK['initial']
    assert data['pressure_max'] == PRESSURE_CLOCK['initial']
    assert data['pressure_warning'] is False


def test_pressure_decrements_on_search(client):
    """Test that searching a location costs pressure."""
    initial = PRESSURE_CLOCK['initial']
    client.post('/api/game/locations/study/search')

    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['pressure_remaining'] == initial - PRESSURE_CLOCK['cost_search']


def test_pressure_decrements_on_interrogate(client):
    """Test that interrogation costs pressure."""
    initial = PRESSURE_CLOCK['initial']
    client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})

    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['pressure_remaining'] == initial - PRESSURE_CLOCK['cost_interrogate']


def test_pressure_in_search_response(client):
    """Test that search response includes pressure_remaining."""
    response = client.post('/api/game/locations/study/search')
    data = response.get_json()
    assert 'pressure_remaining' in data


def test_pressure_in_interrogate_response(client):
    """Test that interrogation response includes pressure_remaining."""
    response = client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})
    data = response.get_json()
    assert 'pressure_remaining' in data


def test_pressure_warning_triggers(client):
    """Test that pressure warning fires at threshold."""
    state = get_session_state(client)
    # Set pressure just above warning threshold
    state["pressure_remaining"] = PRESSURE_CLOCK['warning'] + PRESSURE_CLOCK['cost_search']

    response = client.post('/api/game/locations/garden/search')
    data = response.get_json()
    assert 'pressure_warning' in data
    assert data['pressure_remaining'] == PRESSURE_CLOCK['warning']


def test_pressure_expired_ends_game_on_search(client):
    """Test that running out of pressure ends the game during search."""
    state = get_session_state(client)
    state["pressure_remaining"] = 0 + PRESSURE_CLOCK['cost_search']

    response = client.post('/api/game/locations/garden/search')
    data = response.get_json()
    assert data['status'] == 'failure'
    assert data['pressure_remaining'] == 0

    # Verify game is over
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'complete'
    assert data['game_won'] is False


def test_pressure_expired_ends_game_on_interrogate(client):
    """Test that running out of pressure ends the game during interrogation."""
    state = get_session_state(client)
    state["pressure_remaining"] = 1  # Less than cost_interrogate (2)

    response = client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})
    data = response.get_json()
    assert data['status'] == 'failure'
    assert data['pressure_remaining'] == 0

    # Verify game is over
    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['phase'] == 'complete'
    assert data['game_won'] is False


def test_cannot_search_after_pressure_expired(client):
    """Test that actions are blocked after game ends from pressure."""
    state = get_session_state(client)
    state["pressure_remaining"] = PRESSURE_CLOCK['cost_search']
    client.post('/api/game/locations/garden/search')  # Exhausts pressure

    response = client.post('/api/game/locations/study/search')
    assert response.status_code == 400


def test_cannot_interrogate_after_pressure_expired(client):
    """Test that interrogation is blocked after game ends from pressure."""
    state = get_session_state(client)
    state["pressure_remaining"] = PRESSURE_CLOCK['cost_search']
    client.post('/api/game/locations/garden/search')  # Exhausts pressure

    response = client.post('/api/game/interrogate', json={'suspect_id': SUSPECTS[0]['id']})
    assert response.status_code == 400


def test_pressure_resets_on_new_game(client):
    """Test that pressure resets when starting a new game."""
    state = get_session_state(client)
    state["pressure_remaining"] = 1

    client.post('/api/game/new')

    response = client.get('/api/game/state')
    data = response.get_json()
    assert data['pressure_remaining'] == PRESSURE_CLOCK['initial']


# --- Save/Load tests ---

def test_save_returns_game_state(client):
    """Test that save endpoint returns current game state."""
    client.post('/api/game/locations/study/search')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})

    response = client.get('/api/game/save')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    save = data['save_data']
    assert save['phase'] == 'investigation'
    assert 'poison_vial' in save['clues_discovered']
    assert 'study' in save['locations_visited']
    assert len(save['interrogations']) == 1
    assert save['pressure_remaining'] < PRESSURE_CLOCK['initial']
    assert save['final_accusation'] is None
    assert save['game_won'] is None


def test_load_restores_game_state(client):
    """Test that load endpoint restores saved state."""
    client.post('/api/game/locations/study/search')
    client.post('/api/game/locations/victim_room/search')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})

    save_data = client.get('/api/game/save').get_json()['save_data']

    # Reset and verify clean state
    client.post('/api/game/new')
    assert client.get('/api/game/state').get_json()['clues_discovered_count'] == 0

    # Load saved state
    response = client.post('/api/game/load', json={'save_data': save_data})
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    # Verify restored
    state = client.get('/api/game/state').get_json()
    assert state['clues_discovered_count'] == 2
    assert state['locations_visited_count'] == 2
    assert state['interrogations_count'] == 1
    assert state['pressure_remaining'] == save_data['pressure_remaining']


def test_load_missing_save_data(client):
    """Test load with missing save_data."""
    response = client.post('/api/game/load', json={})
    assert response.status_code == 400


def test_load_missing_keys(client):
    """Test load with incomplete save data."""
    response = client.post('/api/game/load', json={'save_data': {'phase': 'investigation'}})
    assert response.status_code == 400
    assert 'Missing keys' in response.get_json()['message']


def test_load_invalid_phase(client):
    """Test load with invalid phase value."""
    save_data = {
        'phase': 'invalid_phase',
        'clues_discovered': [],
        'locations_visited': [],
        'interrogations': [],
        'pressure_remaining': 10,
        'final_accusation': None,
        'game_won': None,
    }
    response = client.post('/api/game/load', json={'save_data': save_data})
    assert response.status_code == 400
    assert 'Invalid phase' in response.get_json()['message']


def test_load_syncs_clue_discovery_flags(client):
    """Test that load correctly syncs clue discovered flags."""
    client.post('/api/game/locations/study/search')
    save_data = client.get('/api/game/save').get_json()['save_data']

    client.post('/api/game/new')
    client.post('/api/game/load', json={'save_data': save_data})

    clues = client.get('/api/game/clues').get_json()
    assert clues['discovered_count'] == 1
    assert clues['clues'][0]['id'] == 'poison_vial'


def test_save_load_roundtrip_mid_accusation(client):
    """Test save/load roundtrip during accusation phase."""
    client.post('/api/game/locations/study/search')
    client.post('/api/game/locations/victim_room/search')
    client.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
    client.post('/api/game/interrogate', json={'suspect_id': 'dr_hartley'})

    assert client.get('/api/game/state').get_json()['phase'] == 'accusation'

    save_data = client.get('/api/game/save').get_json()['save_data']
    client.post('/api/game/new')
    client.post('/api/game/load', json={'save_data': save_data})

    state = client.get('/api/game/state').get_json()
    assert state['phase'] == 'accusation'

    response = client.post('/api/game/accuse', json={'suspect_id': 'dr_hartley'})
    assert response.get_json()['correct'] is True


# --- Session isolation tests ---

def test_sessions_are_isolated():
    """Test that two clients have completely separate game states."""
    app.config['TESTING'] = True
    reset_game()

    with app.test_client() as client_a:
        client_a.post('/api/game/new')
        # Client A discovers a clue
        client_a.post('/api/game/locations/study/search')
        state_a = client_a.get('/api/game/state').get_json()
        assert state_a['clues_discovered_count'] == 1

        with app.test_client() as client_b:
            client_b.post('/api/game/new')
            # Client B should have no clues
            state_b = client_b.get('/api/game/state').get_json()
            assert state_b['clues_discovered_count'] == 0

            # Client B discovers different clue
            client_b.post('/api/game/locations/victim_room/search')
            state_b = client_b.get('/api/game/state').get_json()
            assert state_b['clues_discovered_count'] == 1

        # Client A still has only 1 clue (no bleed from B)
        state_a = client_a.get('/api/game/state').get_json()
        assert state_a['clues_discovered_count'] == 1


def test_session_persists_across_requests(client):
    """Test that session cookie maintains state between requests."""
    client.post('/api/game/locations/study/search')
    client.post('/api/game/locations/victim_room/search')

    # State should accumulate across requests
    state = client.get('/api/game/state').get_json()
    assert state['clues_discovered_count'] == 2
    assert state['locations_visited_count'] == 2


def test_no_cross_session_interrogation_bleed():
    """Test that interrogation records don't leak between sessions."""
    app.config['TESTING'] = True
    reset_game()

    with app.test_client() as client_a:
        client_a.post('/api/game/new')
        client_a.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
        notes_a = client_a.get('/api/game/interrogations').get_json()
        assert len(notes_a['interrogations']) == 1

        with app.test_client() as client_b:
            client_b.post('/api/game/new')
            notes_b = client_b.get('/api/game/interrogations').get_json()
            assert len(notes_b['interrogations']) == 0

            # B can interrogate same suspect independently
            client_b.post('/api/game/interrogate', json={'suspect_id': 'lady_blackwood'})
            notes_b = client_b.get('/api/game/interrogations').get_json()
            assert len(notes_b['interrogations']) == 1


def test_new_game_resets_only_own_session():
    """Test that new game only resets the calling session, not others."""
    app.config['TESTING'] = True
    reset_game()

    with app.test_client() as client_a:
        client_a.post('/api/game/new')
        client_a.post('/api/game/locations/study/search')

        with app.test_client() as client_b:
            client_b.post('/api/game/new')
            client_b.post('/api/game/locations/hallway/search')

            # B starts a new game — should only reset B
            client_b.post('/api/game/new')
            state_b = client_b.get('/api/game/state').get_json()
            assert state_b['clues_discovered_count'] == 0

        # A is untouched
        state_a = client_a.get('/api/game/state').get_json()
        assert state_a['clues_discovered_count'] == 1


def test_session_cookie_set_on_response(client):
    """Test that session cookie is present in API responses."""
    response = client.get('/api/game/state')
    cookie_header = response.headers.get('Set-Cookie', '')
    assert 'agatha_session=' in cookie_header


def test_parallel_sessions_independent_pressure():
    """Test that pressure clocks are independent per session."""
    app.config['TESTING'] = True
    reset_game()

    with app.test_client() as client_a:
        client_a.post('/api/game/new')
        # A burns 5 pressure (5 searches)
        for loc_id in ['study', 'victim_room', 'hallway', 'victim_desk', 'garden']:
            client_a.post(f'/api/game/locations/{loc_id}/search')
        state_a = client_a.get('/api/game/state').get_json()
        assert state_a['pressure_remaining'] == 5

        with app.test_client() as client_b:
            client_b.post('/api/game/new')
            # B should have full pressure
            state_b = client_b.get('/api/game/state').get_json()
            assert state_b['pressure_remaining'] == PRESSURE_CLOCK['initial']
