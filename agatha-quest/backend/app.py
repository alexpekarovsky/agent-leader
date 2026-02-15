"""Backend API for Agatha Christie-style murder mystery game."""
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from game_data import (
    SUSPECTS, CLUES, LOCATIONS, CASE_INFO, PRESSURE_CLOCK,
    PHASE_INVESTIGATION, PHASE_ACCUSATION, PHASE_COMPLETE
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)

# In-memory game state (will reset on server restart)
game_state = {
    "phase": PHASE_INVESTIGATION,
    "clues_discovered": [],
    "locations_visited": [],
    "interrogations": [],
    "pressure_remaining": PRESSURE_CLOCK["initial"],
    "final_accusation": None,
    "game_won": None
}


def spend_pressure(cost):
    """Decrement pressure clock. Returns dict with warning/expired info."""
    game_state["pressure_remaining"] = max(0, game_state["pressure_remaining"] - cost)
    remaining = game_state["pressure_remaining"]
    result = {"pressure_remaining": remaining}
    if remaining <= 0 and game_state["phase"] != PHASE_COMPLETE:
        game_state["phase"] = PHASE_COMPLETE
        game_state["game_won"] = False
        result["expired"] = True
        result["message"] = "Time has run out! The killer escapes into the night..."
    elif remaining <= PRESSURE_CLOCK["warning"]:
        result["warning"] = True
        result["message"] = f"The clock is ticking! Only {remaining} action(s) remain."
    return result


def maybe_unlock_accusation_phase():
    """Move game to accusation phase when enough evidence is collected."""
    if game_state["phase"] != PHASE_INVESTIGATION:
        return
    if len(game_state["clues_discovered"]) >= 2 and len(game_state["interrogations"]) >= 2:
        game_state["phase"] = PHASE_ACCUSATION


def reset_game():
    """Reset game state to initial values."""
    global game_state
    game_state = {
        "phase": PHASE_INVESTIGATION,
        "clues_discovered": [],
        "locations_visited": [],
        "interrogations": [],
        "pressure_remaining": PRESSURE_CLOCK["initial"],
        "final_accusation": None,
        "game_won": None
    }
    # Reset clue discovery status
    for clue in CLUES:
        clue["discovered"] = False


@app.route('/api/game/new', methods=['POST'])
def new_game():
    """Start a new game."""
    reset_game()
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
    remaining = game_state["pressure_remaining"]
    return jsonify({
        "phase": game_state["phase"],
        "clues_discovered_count": len(game_state["clues_discovered"]),
        "locations_visited_count": len(game_state["locations_visited"]),
        "interrogations_count": len(game_state["interrogations"]),
        "pressure_remaining": remaining,
        "pressure_max": PRESSURE_CLOCK["initial"],
        "pressure_warning": remaining <= PRESSURE_CLOCK["warning"] and game_state["phase"] != PHASE_COMPLETE,
        "final_accusation": game_state["final_accusation"],
        "game_won": game_state["game_won"]
    })


@app.route('/api/game/interrogations', methods=['GET'])
def get_interrogations():
    """Get interrogation records."""
    return jsonify({"interrogations": game_state["interrogations"]})


@app.route('/api/game/suspects', methods=['GET'])
def get_suspects():
    """Get list of all suspects (without revealing secrets)."""
    suspects_public = []
    for suspect in SUSPECTS:
        suspects_public.append({
            "id": suspect["id"],
            "name": suspect["name"],
            "description": suspect["description"],
            "interrogated": suspect["id"] in [i["suspect_id"] for i in game_state["interrogations"]]
        })
    return jsonify({"suspects": suspects_public})


@app.route('/api/game/clues', methods=['GET'])
def get_clues():
    """Get discovered clues."""
    discovered = [clue for clue in CLUES if clue["id"] in game_state["clues_discovered"]]
    return jsonify({
        "clues": discovered,
        "total_clues": len(CLUES),
        "discovered_count": len(discovered)
    })


@app.route('/api/game/clues/<clue_id>/discover', methods=['POST'])
def discover_clue(clue_id):
    """Discover a clue by searching a location."""
    # Find the clue
    clue = next((c for c in CLUES if c["id"] == clue_id), None)

    if not clue:
        return jsonify({"status": "error", "message": "Clue not found"}), 404

    if clue["id"] in game_state["clues_discovered"]:
        return jsonify({"status": "error", "message": "Clue already discovered"}), 400

    # Mark as discovered
    clue["discovered"] = True
    game_state["clues_discovered"].append(clue["id"])
    maybe_unlock_accusation_phase()

    return jsonify({
        "status": "success",
        "message": "Clue discovered!",
        "clue": clue
    })


@app.route('/api/game/interrogate', methods=['POST'])
def interrogate():
    """Interrogate a suspect."""
    if game_state["phase"] == PHASE_COMPLETE:
        return jsonify({"status": "error", "message": "Game is over"}), 400

    data = request.get_json(silent=True) or {}
    suspect_id = data.get("suspect_id")

    if not suspect_id:
        return jsonify({"status": "error", "message": "suspect_id required"}), 400

    # Find the suspect
    suspect = next((s for s in SUSPECTS if s["id"] == suspect_id), None)

    if not suspect:
        return jsonify({"status": "error", "message": "Suspect not found"}), 404

    # Check if already interrogated
    already_interrogated = suspect_id in [i["suspect_id"] for i in game_state["interrogations"]]

    if already_interrogated:
        return jsonify({"status": "error", "message": "Suspect already interrogated"}), 400

    # Spend pressure
    pressure = spend_pressure(PRESSURE_CLOCK["cost_interrogate"])
    if pressure.get("expired"):
        return jsonify({"status": "failure", "message": pressure["message"], "pressure_remaining": 0})

    # Record interrogation
    interrogation = {
        "suspect_id": suspect_id,
        "suspect_name": suspect["name"],
        "alibi": suspect["alibi"],
        "secret_revealed": len(game_state["clues_discovered"]) >= 2  # Reveal secret if 2+ clues found
    }

    if interrogation["secret_revealed"]:
        interrogation["secret"] = suspect["secret"]

    game_state["interrogations"].append(interrogation)
    maybe_unlock_accusation_phase()

    response = {"status": "success", "interrogation": interrogation, "pressure_remaining": pressure["pressure_remaining"]}
    if pressure.get("warning"):
        response["pressure_warning"] = pressure["message"]
    return jsonify(response)


@app.route('/api/game/locations', methods=['GET'])
def get_locations():
    """Get all manor locations with visit status."""
    result = []
    for loc in LOCATIONS:
        result.append({
            "id": loc["id"],
            "name": loc["name"],
            "description": loc["description"],
            "visited": loc["id"] in game_state["locations_visited"],
            "has_clues": len(loc["clue_ids"]) > 0
        })
    return jsonify({"locations": result})


@app.route('/api/game/locations/<location_id>', methods=['GET'])
def get_location(location_id):
    """Get details of a specific location."""
    loc = next((l for l in LOCATIONS if l["id"] == location_id), None)
    if not loc:
        return jsonify({"status": "error", "message": "Location not found"}), 404

    visited = location_id in game_state["locations_visited"]
    # Show which clues were found here (only already-discovered ones)
    found_clues = [c for c in CLUES if c["id"] in loc["clue_ids"] and c["id"] in game_state["clues_discovered"]]

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
    if game_state["phase"] == PHASE_COMPLETE:
        return jsonify({"status": "error", "message": "Game is over"}), 400

    loc = next((l for l in LOCATIONS if l["id"] == location_id), None)
    if not loc:
        return jsonify({"status": "error", "message": "Location not found"}), 404

    # Spend pressure
    pressure = spend_pressure(PRESSURE_CLOCK["cost_search"])
    if pressure.get("expired"):
        return jsonify({"status": "failure", "message": pressure["message"], "pressure_remaining": 0})

    # Mark as visited
    if location_id not in game_state["locations_visited"]:
        game_state["locations_visited"].append(location_id)

    # Discover any undiscovered clues at this location
    newly_found = []
    for clue_id in loc["clue_ids"]:
        clue = next((c for c in CLUES if c["id"] == clue_id), None)
        if clue and clue_id not in game_state["clues_discovered"]:
            clue["discovered"] = True
            game_state["clues_discovered"].append(clue_id)
            newly_found.append(clue)

    maybe_unlock_accusation_phase()

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
    data = request.get_json(silent=True) or {}
    accused_id = data.get("suspect_id")

    if not accused_id:
        return jsonify({"status": "error", "message": "suspect_id required"}), 400

    if game_state["phase"] == PHASE_COMPLETE:
        return jsonify({"status": "error", "message": "Game already complete"}), 400
    if game_state["phase"] != PHASE_ACCUSATION:
        return jsonify({
            "status": "error",
            "message": "Collect more evidence before making a final accusation."
        }), 400

    # Find the suspect
    suspect = next((s for s in SUSPECTS if s["id"] == accused_id), None)

    if not suspect:
        return jsonify({"status": "error", "message": "Suspect not found"}), 404

    # Check if correct
    is_correct = accused_id == CASE_INFO["culprit"]

    game_state["final_accusation"] = {
        "suspect_id": accused_id,
        "suspect_name": suspect["name"]
    }
    game_state["game_won"] = is_correct
    game_state["phase"] = PHASE_COMPLETE

    return jsonify({
        "status": "success",
        "correct": is_correct,
        "message": "You solved the mystery!" if is_correct else "Wrong accusation! The killer escapes...",
        "culprit": CASE_INFO["culprit"] if not is_correct else None
    })


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
