# Blackwood Manor Mystery (Agatha Quest)

A small full-stack murder mystery web game inspired by Agatha Christie-style detective stories.

## Stack
- Backend: Flask API (`agatha-quest/backend`)
- Frontend: Vanilla HTML/CSS/JS (`agatha-quest/frontend`)
- State: In-memory game state (resets on server restart)

## Features
- Start new investigation
- Discover clues at manor locations
- Interrogate suspects
- Reveal deeper secrets as evidence grows
- Make final accusation and get verdict

## Run
```bash
cd agatha-quest/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5001`

## Test
```bash
cd agatha-quest/backend
source .venv/bin/activate
pytest -q
```

## API Endpoints
- `POST /api/game/new`
- `GET /api/game/state`
- `GET /api/game/suspects`
- `GET /api/game/clues`
- `POST /api/game/clues/<clue_id>/discover`
- `POST /api/game/interrogate`
- `GET /api/game/interrogations`
- `POST /api/game/accuse`
- `GET /health`
