"""Backend API for Agatha Christie-style murder mystery game."""
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS

from game_data import (
    SUSPECTS, CLUES, LOCATIONS, CASE_INFO, PRESSURE_CLOCK,
    PHASE_INVESTIGATION, PHASE_ACCUSATION, PHASE_COMPLETE
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)

# Per-session game state storage (keyed by session UUID)
sessions = {}


def make_fresh_state():
    """Create a fresh game state dict."""
    return {
        "phase": PHASE_INVESTIGATION,
        "clues_discovered": [],
        "locations_visited": [],
        "interrogations": [],
        "pressure_remaining": PRESSURE_CLOCK["initial"],
        "final_accusation": None,
        "game_won": None,
    }


def get_game_state():
    """Get game state for the current session, creating one if needed."""
    if "game_state" not in g:
        sid = request.cookies.get("agatha_session")
        if sid and sid in sessions:
            g.session_id = sid
        else:
            sid = str(uuid.uuid4())
            g.session_id = sid
            sessions[sid] = make_fresh_state()
        g.game_state = sessions[sid]
    return g.game_state


@app.after_request
def set_session_cookie(response):
    """Attach session cookie to every API response."""
    sid = g.get("session_id")
    if sid:
        response.set_cookie("agatha_session", sid, httponly=True, samesite="Lax")
    return response


def reset_game():
    """Clear all sessions. Backward-compatible for test fixtures."""
    sessions.clear()


def spend_pressure(state, cost):
    """Decrement pressure clock. Returns dict with warning/expired info."""
    state["pressure_remaining"] = max(0, state["pressure_remaining"] - cost)
    remaining = state["pressure_remaining"]
    result = {"pressure_remaining": remaining}
    if remaining <= 0 and state["phase"] != PHASE_COMPLETE:
        state["phase"] = PHASE_COMPLETE
        state["game_won"] = False
        result["expired"] = True
        result["message"] = "Time has run out! The killer escapes into the night..."
    elif remaining <= PRESSURE_CLOCK["warning"]:
        result["warning"] = True
        result["message"] = f"The clock is ticking! Only {remaining} action(s) remain."
    return result


def maybe_unlock_accusation_phase(state):
    """Move game to accusation phase when enough evidence is collected."""
    if state["phase"] != PHASE_INVESTIGATION:
        return
    if len(state["clues_discovered"]) >= 2 and len(state["interrogations"]) >= 2:
        state["phase"] = PHASE_ACCUSATION


def _clue_dict(clue):
    """Return a safe copy of clue data (no mutable reference to module-level CLUES)."""
    return {"id": clue["id"], "name": clue["name"],
            "description": clue["description"], "location": clue["location"]}


@app.route('/api/game/new', methods=['POST'])
def new_game():
    """Start a new game (resets current session)."""
    sid = request.cookies.get("agatha_session") or str(uuid.uuid4())
    g.session_id = sid
    sessions[sid] = make_fresh_state()
    g.game_state = sessions[sid]
    return jsonify({
        "status": "success",
        "message": "New game started",
        "case_info": {
            "victim": CASE_INFO["victim"],
            "location": CASE_INFO["location"],
            "cause_of_death": CASE_INFO["cause_of_death"],
            "time_of_death": CASE_INFO["time_of_death"]
        }
    })


@app.route('/api/game/state', methods=['GET'])
def get_state():
    """Get current game state."""
    state = get_game_state()
    remaining = state["pressure_remaining"]
    return jsonify({
        "phase": state["phase"],
        "clues_discovered_count": len(state["clues_discovered"]),
        "locations_visited_count": len(state["locations_visited"]),
        "interrogations_count": len(state["interrogations"]),
        "pressure_remaining": remaining,
        "pressure_max": PRESSURE_CLOCK["initial"],
        "pressure_warning": remaining <= PRESSURE_CLOCK["warning"] and state["phase"] != PHASE_COMPLETE,
        "final_accusation": state["final_accusation"],
        "game_won": state["game_won"]
    })


@app.route('/api/game/interrogations', methods=['GET'])
def get_interrogations():
    """Get interrogation records."""
    state = get_game_state()
    return jsonify({"interrogations": state["interrogations"]})


@app.route('/api/game/suspects', methods=['GET'])
def get_suspects():
    """Get list of all suspects (without revealing secrets)."""
    state = get_game_state()
    suspects_public = []
    for suspect in SUSPECTS:
        suspects_public.append({
            "id": suspect["id"],
            "name": suspect["name"],
            "description": suspect["description"],
            "interrogated": suspect["id"] in [i["suspect_id"] for i in state["interrogations"]]
        })
    return jsonify({"suspects": suspects_public})


@app.route('/api/game/clues', methods=['GET'])
def get_clues():
    """Get discovered clues."""
    state = get_game_state()
    discovered = [_clue_dict(c) for c in CLUES if c["id"] in state["clues_discovered"]]
    return jsonify({
        "clues": discovered,
        "total_clues": len(CLUES),
        "discovered_count": len(discovered)
    })


@app.route('/api/game/clues/<clue_id>/discover', methods=['POST'])
def discover_clue(clue_id):
    """Discover a clue by searching a location."""
    state = get_game_state()
    clue = next((c for c in CLUES if c["id"] == clue_id), None)

    if not clue:
        return jsonify({"status": "error", "message": "Clue not found"}), 404

    if clue["id"] in state["clues_discovered"]:
        return jsonify({"status": "error", "message": "Clue already discovered"}), 400

    state["clues_discovered"].append(clue["id"])
    maybe_unlock_accusation_phase(state)

    clue_resp = _clue_dict(clue)
    clue_resp["discovered"] = True
    return jsonify({
        "status": "success",
        "message": "Clue discovered!",
        "clue": clue_resp
    })


@app.route('/api/game/interrogate', methods=['POST'])
def interrogate():
    """Interrogate a suspect."""
    state = get_game_state()
    if state["phase"] == PHASE_COMPLETE:
        return jsonify({"status": "error", "message": "Game is over"}), 400

    data = request.get_json(silent=True) or {}
    suspect_id = data.get("suspect_id")

    if not suspect_id:
        return jsonify({"status": "error", "message": "suspect_id required"}), 400

    suspect = next((s for s in SUSPECTS if s["id"] == suspect_id), None)

    if not suspect:
        return jsonify({"status": "error", "message": "Suspect not found"}), 404

    already_interrogated = suspect_id in [i["suspect_id"] for i in state["interrogations"]]

    if already_interrogated:
        return jsonify({"status": "error", "message": "Suspect already interrogated"}), 400

    pressure = spend_pressure(state, PRESSURE_CLOCK["cost_interrogate"])
    if pressure.get("expired"):
        return jsonify({"status": "failure", "message": pressure["message"], "pressure_remaining": 0})

    interrogation = {
        "suspect_id": suspect_id,
        "suspect_name": suspect["name"],
        "alibi": suspect["alibi"],
        "secret_revealed": len(state["clues_discovered"]) >= 2
    }

    if interrogation["secret_revealed"]:
        interrogation["secret"] = suspect["secret"]

    state["interrogations"].append(interrogation)
    maybe_unlock_accusation_phase(state)

    response = {"status": "success", "interrogation": interrogation, "pressure_remaining": pressure["pressure_remaining"]}
    if pressure.get("warning"):
        response["pressure_warning"] = pressure["message"]
    return jsonify(response)


@app.route('/api/game/locations', methods=['GET'])
def get_locations():
    """Get all manor locations with visit status."""
    state = get_game_state()
    result = []
    for loc in LOCATIONS:
        result.append({
            "id": loc["id"],
            "name": loc["name"],
            "description": loc["description"],
            "visited": loc["id"] in state["locations_visited"],
            "has_clues": len(loc["clue_ids"]) > 0
        })
    return jsonify({"locations": result})


@app.route('/api/game/locations/<location_id>', methods=['GET'])
def get_location(location_id):
    """Get details of a specific location."""
    state = get_game_state()
    loc = next((l for l in LOCATIONS if l["id"] == location_id), None)
    if not loc:
        return jsonify({"status": "error", "message": "Location not found"}), 404

    visited = location_id in state["locations_visited"]
    found_clues = [_clue_dict(c) for c in CLUES
                   if c["id"] in loc["clue_ids"] and c["id"] in state["clues_discovered"]]

    return jsonify({
        "id": loc["id"],
        "name": loc["name"],
        "description": loc["description"],
        "visited": visited,
        "clues_found": found_clues
    })


@app.route('/api/game/locations/<location_id>/search', methods=['POST'])
def search_location(location_id):
    """Search a location to discover clues tied to it."""
    state = get_game_state()
    if state["phase"] == PHASE_COMPLETE:
        return jsonify({"status": "error", "message": "Game is over"}), 400

    loc = next((l for l in LOCATIONS if l["id"] == location_id), None)
    if not loc:
        return jsonify({"status": "error", "message": "Location not found"}), 404

    pressure = spend_pressure(state, PRESSURE_CLOCK["cost_search"])
    if pressure.get("expired"):
        return jsonify({"status": "failure", "message": pressure["message"], "pressure_remaining": 0})

    if location_id not in state["locations_visited"]:
        state["locations_visited"].append(location_id)

    newly_found = []
    for clue_id in loc["clue_ids"]:
        clue = next((c for c in CLUES if c["id"] == clue_id), None)
        if clue and clue_id not in state["clues_discovered"]:
            state["clues_discovered"].append(clue_id)
            newly_found.append(_clue_dict(clue))

    maybe_unlock_accusation_phase(state)

    response = {
        "status": "success",
        "clues_found": newly_found,
        "location": loc["name"],
        "pressure_remaining": pressure["pressure_remaining"]
    }
    if newly_found:
        response["message"] = f"You found {len(newly_found)} clue(s)!"
    else:
        response["message"] = "Nothing new found here."
    if pressure.get("warning"):
        response["pressure_warning"] = pressure["message"]
    return jsonify(response)


@app.route('/api/game/accuse', methods=['POST'])
def accuse():
    """Make final accusation."""
    state = get_game_state()
    data = request.get_json(silent=True) or {}
    accused_id = data.get("suspect_id")

    if not accused_id:
        return jsonify({"status": "error", "message": "suspect_id required"}), 400

    if state["phase"] == PHASE_COMPLETE:
        return jsonify({"status": "error", "message": "Game already complete"}), 400
    if state["phase"] != PHASE_ACCUSATION:
        return jsonify({
            "status": "error",
            "message": "Collect more evidence before making a final accusation."
        }), 400

    suspect = next((s for s in SUSPECTS if s["id"] == accused_id), None)

    if not suspect:
        return jsonify({"status": "error", "message": "Suspect not found"}), 404

    is_correct = accused_id == CASE_INFO["culprit"]

    state["final_accusation"] = {
        "suspect_id": accused_id,
        "suspect_name": suspect["name"]
    }
    state["game_won"] = is_correct
    state["phase"] = PHASE_COMPLETE

    return jsonify({
        "status": "success",
        "correct": is_correct,
        "message": "You solved the mystery!" if is_correct else "Wrong accusation! The killer escapes...",
        "culprit": CASE_INFO["culprit"] if not is_correct else None
    })


@app.route('/api/game/save', methods=['GET'])
def save_game():
    """Export current game state for save/load continuity."""
    state = get_game_state()
    return jsonify({
        "status": "success",
        "save_data": {
            "phase": state["phase"],
            "clues_discovered": list(state["clues_discovered"]),
            "locations_visited": list(state["locations_visited"]),
            "interrogations": list(state["interrogations"]),
            "pressure_remaining": state["pressure_remaining"],
            "final_accusation": state["final_accusation"],
            "game_won": state["game_won"]
        }
    })


@app.route('/api/game/load', methods=['POST'])
def load_game():
    """Restore game state from save data."""
    data = request.get_json(silent=True) or {}
    save_data = data.get("save_data")

    if not save_data:
        return jsonify({"status": "error", "message": "save_data required"}), 400

    required_keys = {"phase", "clues_discovered", "locations_visited",
                     "interrogations", "pressure_remaining", "final_accusation", "game_won"}
    missing = required_keys - set(save_data.keys())
    if missing:
        return jsonify({"status": "error", "message": f"Missing keys: {', '.join(sorted(missing))}"}), 400

    valid_phases = {PHASE_INVESTIGATION, PHASE_ACCUSATION, PHASE_COMPLETE}
    if save_data["phase"] not in valid_phases:
        return jsonify({"status": "error", "message": "Invalid phase value"}), 400

    # Get or create session, then replace its state
    sid = request.cookies.get("agatha_session") or str(uuid.uuid4())
    g.session_id = sid
    sessions[sid] = {
        "phase": save_data["phase"],
        "clues_discovered": list(save_data["clues_discovered"]),
        "locations_visited": list(save_data["locations_visited"]),
        "interrogations": list(save_data["interrogations"]),
        "pressure_remaining": save_data["pressure_remaining"],
        "final_accusation": save_data["final_accusation"],
        "game_won": save_data["game_won"],
    }
    g.game_state = sessions[sid]

    return jsonify({"status": "success", "message": "Game loaded"})


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "agatha-quest-backend"})


@app.route("/", methods=["GET"])
def frontend_index():
    """Serve the game frontend."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>", methods=["GET"])
def frontend_assets(path: str):
    """Serve static frontend assets."""
    return send_from_directory(FRONTEND_DIR, path)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
