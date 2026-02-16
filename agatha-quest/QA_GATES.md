# Agatha Quest: Validation and Release Gates

## Test Pyramid

### Unit Tests (Backend)
- **Suite**: `pytest agatha-quest/backend/tests/ -v`
- **Coverage**: All API endpoints, game state transitions, pressure clock, location exploration
- **Gate**: 100% pass, 0 failures
- **Current**: 61 tests (50 unit + 11 regression)

### Unit Tests (Frontend)
- **Suite**: Manual browser verification (no JS test framework in current stack)
- **Coverage**: Component rendering, user interactions, API response handling
- **Gate**: Manual smoke test passes

### Integration Tests
- **Suite**: Backend API end-to-end game flow tests
- **Coverage**: Full game lifecycle (new game -> explore -> interrogate -> accuse -> win/lose)
- **Tests**: `test_full_game_flow`, `test_full_game_flow_with_locations`
- **Gate**: All integration tests pass

### Manual Smoke Test
- Start backend server (`python app.py`)
- Open frontend in browser (http://localhost:5001)
- Play through one complete game (win path)
- Play through one complete game (lose path - wrong accusation)
- Verify pressure clock depletes and game ends on expiration

## Release Gate Checklist

### Pre-Release
- [ ] All backend unit tests pass (`pytest tests/ -v`)
- [ ] No Python syntax errors (`python -m py_compile app.py game_data.py`)
- [ ] Server starts without errors (`python app.py`)
- [ ] Frontend loads in browser at `/`
- [ ] API health check returns 200 (`GET /health`)

### Functional Gates
- [ ] New game resets all state (clues, locations, pressure, interrogations)
- [ ] Location search discovers correct clues
- [ ] Interrogation reveals secrets after 2+ clues found
- [ ] Accusation phase unlocks after 2+ clues AND 2+ interrogations
- [ ] Correct accusation wins the game
- [ ] Wrong accusation loses the game
- [ ] Pressure clock decrements on search (cost 1) and interrogation (cost 2)
- [ ] Pressure warning triggers at threshold (3 remaining)
- [ ] Pressure expiration ends game in failure
- [ ] Actions blocked after game completion

### API Contract Gates
- [ ] All endpoints return valid JSON
- [ ] Error responses use proper HTTP status codes (400, 404)
- [ ] No secrets leaked in suspect list endpoint
- [ ] Pressure state included in `/api/game/state`

## Rollback Criteria

### Automatic Rollback Triggers
- Backend tests fail after merge (any test failure)
- Server crashes on startup
- Health endpoint returns non-200

### Manual Rollback Triggers
- Game state corruption (incorrect phase transitions)
- Security issue (secrets exposed in public endpoints)
- Data loss (state not resetting on new game)

### Rollback Procedure
1. `git revert <commit>` the failing change
2. Verify tests pass on reverted state
3. Restart server
4. Run smoke test
