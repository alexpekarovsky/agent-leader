# Agatha Quest: Validation and Release Gates

## Test Pyramid

### Unit Tests (Backend)
- **Suite**: `cd agatha-quest/backend && source venv/bin/activate && pytest tests/ -v`
- **Coverage**: All API endpoints, game state transitions, pressure clock, location exploration, session isolation, save/load
- **Gate**: 100% pass, 0 failures
- **Current**: 74 tests (52 test_api + 5 test_app + 11 test_regression + 6 session isolation)
- **Last run**: 74 passed in 0.54s (Python 3.14.3, pytest 9.0.2)

### Unit Tests (Frontend)
- **Suite**: Manual browser verification (no JS test framework in current stack)
- **Coverage**: Component rendering, user interactions, API response handling
- **Gate**: Manual smoke test passes

### Integration Tests
- **Suite**: Backend API end-to-end game flow tests
- **Coverage**: Full game lifecycle (new game -> explore -> interrogate -> accuse -> win/lose)
- **Tests**: `test_full_game_flow`, `test_full_game_flow_with_locations`, `test_regression_win_via_locations`, `test_regression_win_via_direct_clues`
- **Gate**: All integration tests pass

### Session Isolation Tests
- **Suite**: 6 dedicated session tests in test_api.py
- **Coverage**: Cross-session state isolation, cookie persistence, parallel pressure independence
- **Tests**: `test_sessions_are_isolated`, `test_session_persists_across_requests`, `test_no_cross_session_interrogation_bleed`, `test_new_game_resets_only_own_session`, `test_session_cookie_set_on_response`, `test_parallel_sessions_independent_pressure`

### Manual Smoke Test
- Start backend server (`python app.py`)
- Open frontend in browser (http://localhost:5001)
- Play through one complete game (win path)
- Play through one complete game (lose path - wrong accusation)
- Verify pressure clock depletes and game ends on expiration
- Verify all 6 locations are visible and searchable

## Release Gate Checklist

### Pre-Release
- [x] All backend unit tests pass (`pytest tests/ -v` -- 74/74)
- [x] No Python syntax errors (`python -m py_compile app.py game_data.py`)
- [x] Server starts without errors (`python app.py`)
- [x] Frontend loads in browser at `/`
- [x] API health check returns 200 (`GET /health`)

### Functional Gates
- [x] New game resets all state (clues, locations, pressure, interrogations)
- [x] Location search discovers correct clues (all 6 locations mapped)
- [x] Interrogation reveals secrets after 2+ clues found
- [x] Accusation phase unlocks after 2+ clues AND 2+ interrogations
- [x] Correct accusation wins the game
- [x] Wrong accusation loses the game
- [x] Pressure clock decrements on search (cost 1) and interrogation (cost 2)
- [x] Pressure warning triggers at threshold (3 remaining)
- [x] Pressure expiration ends game in failure
- [x] Actions blocked after game completion
- [x] Session isolation: concurrent players have independent game state

### API Contract Gates
- [x] All endpoints return valid JSON
- [x] Error responses use proper HTTP status codes (400, 404)
- [x] No secrets leaked in suspect list endpoint
- [x] Pressure state included in `/api/game/state`
- [x] Session cookie (`agatha_session`) set on all responses

### Visual Quality Gates
- [x] Painterly cinematic art pass applied (dark manor theme)
- [x] Playfair Display + Crimson Text typography hierarchy
- [x] Ornate gold corner-framed panels
- [x] Animated fog layers and cinematic vignette
- [x] Scene-specific palette shifts on win/loss
- [x] Pressure clock with glow effects and warning pulse
- [x] Desktop and mobile responsive layouts

## Rollback Criteria

### Automatic Rollback Triggers
- Backend tests fail after merge (any test failure)
- Server crashes on startup
- Health endpoint returns non-200

### Manual Rollback Triggers
- Game state corruption (incorrect phase transitions)
- Security issue (secrets exposed in public endpoints)
- Data loss (state not resetting on new game)
- Session bleed (cross-player state contamination)

### Rollback Procedure
1. `git revert <commit>` the failing change
2. Verify tests pass on reverted state
3. Restart server
4. Run smoke test
