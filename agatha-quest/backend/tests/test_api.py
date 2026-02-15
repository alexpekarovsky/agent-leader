"""
Test suite for Agatha Quest backend API.
"""
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, reset_game
from game_data import SUSPECTS, CLUES, CASE_INFO


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        reset_game()  # Reset before each test
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
