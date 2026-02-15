# Agatha Quest Backend API

Backend API for an Agatha Christie-style murder mystery game.

## Setup

```bash
cd agatha-quest/backend
pip install -r requirements.txt
```

## Run Server

```bash
python app.py
```

Server runs on http://localhost:5001

## Run Tests

```bash
pytest tests/ -v
```

## API Endpoints

### Start New Game
`POST /api/game/new`

### Get Game State
`GET /api/game/state`

### Get Suspects
`GET /api/game/suspects`

### Get Discovered Clues
`GET /api/game/clues`

### Discover a Clue
`POST /api/game/clues/<clue_id>/discover`

### Interrogate Suspect
`POST /api/game/interrogate`
```json
{
  "suspect_id": "dr_hartley"
}
```

### Make Final Accusation
`POST /api/game/accuse`
```json
{
  "suspect_id": "dr_hartley"
}
```

## Game Mechanics

1. Players investigate a murder at Blackwood Manor
2. Discover clues by searching locations
3. Interrogate suspects (secrets revealed after finding 2+ clues)
4. Make final accusation to win or lose

## Data Model

- 4 suspects with alibis and secrets
- 4 discoverable clues
- In-memory game state tracking
