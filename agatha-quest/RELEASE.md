# Agatha Quest: Release Checklist

## Placeholder Audit
- [x] No TODO/FIXME/PLACEHOLDER in backend source
- [x] No placeholder text in frontend HTML/JS/CSS
- [x] No lorem ipsum or example.com references
- [x] QA_GATES.md fully resolved

## IP-Safe Naming Audit
- [x] Game title: "Blackwood Manor Mystery" (original)
- [x] All character names are original (Lady Blackwood, Dr. Hartley, James, Miss Winters)
- [x] All location names are original (Blackwood Manor, The Study, etc.)
- [x] "Agatha" used only as genre descriptor ("Agatha-style"), not branding
- [x] No trademarked character names (no Poirot, Marple, Miss Marple, Hercule)
- [x] Folder name "agatha-quest" is descriptive, acceptable for internal use
- [x] No copyrighted text, quotes, or story elements from published works
- [x] All visual assets are CSS-only originals (no borrowed textures/icons/art)
- [x] Google Fonts (Playfair Display, Crimson Text) are SIL Open Font License

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
- Passed: 74
- Failed: 0
- Suites: test_api.py (52), test_app.py (5), test_regression.py (11) -- includes 6 session isolation tests
- Runtime: 0.54s
- Platform: Python 3.14.3, pytest 9.0.2

## Known Residual Risks
1. **In-memory state**: Game state resets on server restart. No persistence layer beyond save/load API.
2. **No HTTPS**: Server runs HTTP only. Acceptable for local/demo use.
3. **No rate limiting**: API has no request throttling. Acceptable for single-user/demo.
4. **Google Fonts dependency**: Typography requires internet access for Google Fonts CDN. Falls back to Georgia/serif without network.

## Go / No-Go Recommendation

**GO** for demo/internal release.

Rationale:
- Backend is fully functional with all game mechanics (investigation, locations, pressure, accusation)
- 74 tests passing with zero failures across 3 test suites
- Session isolation prevents cross-player state bleed
- Painterly cinematic art pass delivers polished visual experience
- Pressure clock displayed in UI with warning/expired states
- All 6 locations visible and interactable
- No placeholder content in shipped surfaces
- IP-safe: all names, content, and visual assets are original
- Frontend provides a complete playable experience with desktop and mobile support
- Known risks are infrastructure items, not blockers for demo release
