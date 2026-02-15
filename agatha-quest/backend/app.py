"""Backend API for Agatha Christie-style murder mystery game."""
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from game_data import (
    SUSPECTS, CLUES, CASE_INFO,
    PHASE_INVESTIGATION, PHASE_ACCUSATION, PHASE_COMPLETE
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)

# In-memory game state (will reset on server restart)
game_state = {
    "phase": PHASE_INVESTIGATION,
    "clues_discovered": [],
    "interrogations": [],
    "final_accusation": None,
    "game_won": None
}


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
        "interrogations": [],
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
    return jsonify({
        "phase": game_state["phase"],
        "clues_discovered_count": len(game_state["clues_discovered"]),
        "interrogations_count": len(game_state["interrogations"]),
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

    return jsonify({
        "status": "success",
        "interrogation": interrogation
    })


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
