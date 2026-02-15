import pytest

from app import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.post("/api/game/new")
        yield c


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_new_game_and_state(client):
    res = client.get("/api/game/state")
    assert res.status_code == 200
    data = res.get_json()
    assert data["phase"] == "investigation"
    assert data["clues_discovered_count"] == 0


def test_discover_clue(client):
    res = client.post("/api/game/clues/poison_vial/discover")
    assert res.status_code == 200
    data = res.get_json()
    assert data["clue"]["id"] == "poison_vial"

    res2 = client.get("/api/game/clues")
    assert res2.status_code == 200
    assert res2.get_json()["discovered_count"] == 1


def test_interrogate_and_interrogations_endpoint(client):
    res = client.post("/api/game/interrogate", json={"suspect_id": "dr_hartley"})
    assert res.status_code == 200

    res2 = client.get("/api/game/interrogations")
    assert res2.status_code == 200
    payload = res2.get_json()
    assert len(payload["interrogations"]) == 1
    assert payload["interrogations"][0]["suspect_id"] == "dr_hartley"


def test_accuse_success(client):
    # Unlock accusation phase by meeting evidence requirements
    client.post("/api/game/clues/poison_vial/discover")
    client.post("/api/game/clues/torn_letter/discover")
    client.post("/api/game/interrogate", json={"suspect_id": "dr_hartley"})
    client.post("/api/game/interrogate", json={"suspect_id": "lady_blackwood"})

    res = client.post("/api/game/accuse", json={"suspect_id": "dr_hartley"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["correct"] is True
