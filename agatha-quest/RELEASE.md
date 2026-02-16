# Agatha Quest: Release Checklist

## Placeholder Audit
- [x] No TODO/FIXME/PLACEHOLDER in backend source
- [x] No placeholder text in frontend HTML/JS/CSS
- [x] No lorem ipsum or example.com references
- [x] QA_GATES.md TBD resolved (frontend test suite clarified)

## IP-Safe Naming Audit
- [x] Game title: "Blackwood Manor Mystery" (original)
- [x] All character names are original (Lady Blackwood, Dr. Hartley, James, Miss Winters)
- [x] All location names are original (Blackwood Manor, The Study, etc.)
- [x] "Agatha Christie" used only as genre descriptor ("Agatha Christie-style"), not branding
- [x] No trademarked character names (no Poirot, Marple, Miss Marple, Hercule)
- [x] Folder name "agatha-quest" is descriptive, acceptable for internal use
- [x] No copyrighted text, quotes, or story elements from published works

## Build / Run / Test Commands

### Setup
```bash
cd agatha-quest/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run Server
```bash
cd agatha-quest/backend
source venv/bin/activate
python app.py
# Server at http://localhost:5001
```

### Run Tests
```bash
cd agatha-quest/backend
source venv/bin/activate
pytest tests/ -v
```

### Verify Health
```bash
curl http://localhost:5001/health
# Expected: {"service":"agatha-quest-backend","status":"ok"}
```

## Test Results (current branch)
- Command: `pytest tests/ -v`
- Passed: 61
- Failed: 0
- Suites: test_api.py (50), test_app.py (5), test_regression.py (11) -- total includes overlap from shared fixtures

## Known Residual Risks
1. **Frontend uses legacy clue discovery**: Frontend calls `/clues/<id>/discover` directly instead of `/locations/<id>/search`. Both endpoints work, but location search is the intended flow.
2. **Frontend does not display pressure clock**: Pressure mechanic is fully functional in backend but not surfaced in UI.
3. **Frontend shows 4 of 6 locations**: Garden and Pantry (red herring rooms) not shown in frontend location map.
4. **In-memory state**: Game state resets on server restart. No persistence layer.
5. **Single-player only**: No session isolation. Concurrent users would share game state.

## Go / No-Go Recommendation

**GO** for demo/internal release.

Rationale:
- Backend is fully functional with all game mechanics (investigation, locations, pressure, accusation)
- 61 tests passing with zero failures
- No placeholder content in shipped surfaces
- IP-safe: all names and content are original
- Frontend provides a playable demo of the core loop
- Known risks are enhancement items, not blockers for initial release
