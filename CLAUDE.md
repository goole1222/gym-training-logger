# CLAUDE.md — Notes for Future Claude Sessions

## Project: Gym Training Logger

### Purpose
A CLI gym log built with **pure Python standard library** (no pip installs).
Target users: beginners who want to track weight progression.

### File Responsibilities
| File | Role |
|------|------|
| `main.py` | CLI loop, menu, user prompts, display formatting |
| `storage.py` | All file I/O (`load_data`, `save_data`), validation helpers |
| `suggest.py` | Progressive overload calculation and printing |
| `training.json` | Auto-created data file (never commit real data) |

### Coding Conventions
- No external libraries. Standard library only.
- Type hints on function signatures where they add clarity.
- Comments explain *why*, not just what.
- Validation lives in `storage.py`; display/formatting lives in `main.py`.
- Auto-save only happens on menu option `0` (Save & Exit).

### Data Schema (v1)
```json
{
  "meta": { "created_at": "...", "updated_at": "...", "version": 1 },
  "records": [
    { "date": "YYYY-MM-DD", "exercise": "str", "sets": 3, "reps": 8,
      "weight": 60.0, "note": "str" }
  ]
}
```

### Suggestion Logic (suggest.py)
- reps >= 8 AND sets >= 3 → +2.5 kg (or +1.25 if weight < 30 kg)
- reps < 5 → Maintain weight, improve form
- Otherwise → +1.25 kg

### Common Extension Points
- **New menu item**: add an `action_*` function in `main.py`, register it in `ACTIONS` dict.
- **New validation**: add a `validate_*` function in `storage.py`.
- **Schema change**: bump `SCHEMA_VERSION`, add migration logic in `load_data`.

### Testing Checklist (manual)
1. First run: confirm `training.json` is created automatically.
2. Add a record with blank date → should default to today.
3. Enter negative weight → should re-prompt.
4. Enter 0 sets → should re-prompt.
5. Add 3+ records for one exercise with reps >= 8 → suggestions should say "Increase".
6. Save & Exit → re-run and confirm records persist.
