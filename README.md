# Gym Training Logger

A command-line tool for logging gym workouts, tracking progressive overload, and sending daily training reminders via Gmail.

**No external libraries required — pure Python 3.10+.**

---

## Features

- **Template-based logging** — create workout templates (e.g. "Push Day") and log an entire session in one go; skip individual exercises with `s`
- **Progressive overload suggestions** — weight-aware trend analysis tells you when to increase, maintain, or deload
- **Schedule + email reminders** — set a weekly training schedule; `notify.py` sends a morning email with today's plan and suggested weights
- **Training history** — view, filter, and edit past records
- **Weight trend chart** — ASCII chart showing weight progression for any exercise
- **Export** — generate a plain-text or JSON summary of all exercises
- **Auto-save** — data is saved automatically on exit (including Ctrl+C)

---

## Quick Start

```bash
# 1. Put all .py files in the same folder
# 2. Run
python main.py

# Use a custom data file
python main.py --file my_log.json
```

`training.json` is created automatically the first time you save.

---

## File Overview

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point — menus, prompts, actions |
| `storage.py` | JSON I/O, validation helpers, export logic |
| `suggest.py` | Progressive overload suggestion engine |
| `notify.py` | Standalone email notifier (run via Task Scheduler / cron) |
| `notify_config.example.json` | Template for Gmail credentials |

---

## Menu Overview

```
  1) Log workout (from template)  — pick a template and log today's session
  2) Show last records            — view recent sessions (newest first)
  3) Search records               — filter by exercise name keyword
  4) Suggestions                  — progressive overload advice per exercise
  5) Weight trend chart           — ASCII chart for one exercise
  6) Export summary               — stats per exercise → .txt / .json
  7) Edit record                  — correct a past entry
  8) Delete record                — remove a past entry
  9) Manage templates             — create / view / delete workout templates
  10) Edit weekly schedule        — set which template runs on which day
  0) Save & Exit
```

---

## Setting Up Email Notifications

1. Enable **2-Step Verification** on your Google account.
2. Generate an **App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
3. Copy `notify_config.example.json` → `notify_config.json` and fill in your details:

```json
{
  "email_from":   "you@gmail.com",
  "email_to":     "you@gmail.com",
  "app_password": "xxxx xxxx xxxx xxxx"
}
```

4. Add a `schedule` block to `training.json` (via menu option 10), or manually:

```json
"schedule": {
  "monday":    "Push Day",
  "thursday":  "Push Day",
  "saturday":  "Leg Day"
}
```

5. Test manually:

```bash
python notify.py
```

6. Automate with **Windows Task Scheduler** (Windows) or a **cron job** (Linux/macOS) to run every morning.

---

## Progressive Overload Logic

`suggest.py` applies three priority rules per exercise:

| Priority | Condition | Action |
|----------|-----------|--------|
| 1 | Two consecutive real rep declines (weight-adjusted) | **Deload** — reduce weight |
| 2 | Single-session rep drop ≥ 2 (weight-adjusted) | **Maintain** — consolidate |
| 3 | reps ≥ 8 and sets ≥ 3 | **Increase** weight |

**Weight-adjusted** means: for every 2.5 kg increase in load, 1 expected rep drop is forgiven before triggering a penalty. This prevents false "Maintain" signals after a deliberate weight increase.

---

## Data Storage

- All data is stored in `training.json`.
- Automatic backups are saved to `backups/` (up to 10 kept) on every save.
- Both `training.json` and `backups/` are excluded from git (see `.gitignore`).

---

## Tips

- Leave the date blank to default to today; type a single number (e.g. `9`) for the 9th of this month.
- When logging from a template, type `s` at the weight prompt to skip an exercise.
- After template exercises, the app asks if you did any extra exercises.
- Weight `0` means a bodyweight exercise (e.g. pull-ups).
- The app auto-saves on Ctrl+C — no data loss if you close the terminal.
