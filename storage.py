"""
storage.py — File I/O, validation helpers, and export logic for the Training Logger.

All file reads/writes go through this module.
Validation functions are centralised here so main.py never parses raw strings directly.
"""

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, date
from statistics import mean
from typing import Optional

# Default data file name (used when --file is not specified).
DEFAULT_DATA_FILE = "training.json"

# Schema version — bump this if the JSON structure changes in a breaking way.
SCHEMA_VERSION = 1

# Maximum number of backup files to keep in the backups/ directory.
MAX_BACKUPS = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _empty_schema() -> dict:
    """Return a fresh, empty data structure with correct meta fields."""
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "meta": {
            "created_at": now,
            "updated_at": now,
            "version": SCHEMA_VERSION,
        },
        # templates 是一個清單，裡面放使用者建立的訓練模板
        # 每個模板長這樣：{"name": "Push Day", "items": [...]}
        "templates": [],
        "records": [],
    }


def _ensure_ids(records: list[dict]) -> list[dict]:
    """
    Backward-compatibility fix: assign a UUID to any record that lacks one.
    This lets V1.0 data files work seamlessly after upgrading to V1.1.
    """
    for rec in records:
        if not rec.get("id"):
            rec["id"] = str(uuid.uuid4())
    return records


def _create_backup(path: str) -> None:
    """
    Copy the existing data file to backups/<basename>_YYYYMMDD_HHMMSS.json.
    Silently prunes the oldest files if there are more than MAX_BACKUPS.
    Does nothing if the source file does not exist.
    """
    if not os.path.exists(path):
        return

    # Put backups/ next to the data file, wherever that is.
    data_dir = os.path.dirname(os.path.abspath(path))
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(path))[0]
    backup_name = f"{base_name}_{timestamp}.json"
    backup_path = os.path.join(backup_dir, backup_name)

    shutil.copy2(path, backup_path)

    # Prune oldest backups so we never keep more than MAX_BACKUPS.
    all_backups = sorted(
        f for f in os.listdir(backup_dir) if f.endswith(".json")
    )
    while len(all_backups) > MAX_BACKUPS:
        oldest = all_backups.pop(0)
        try:
            os.unlink(os.path.join(backup_dir, oldest))
        except OSError:
            pass  # Non-fatal: just leave the file if we can't delete it.


# ---------------------------------------------------------------------------
# Public I/O functions
# ---------------------------------------------------------------------------

def load_data(path: str = DEFAULT_DATA_FILE) -> dict:
    """
    Load training data from *path*.

    - If the file does not exist, return an empty schema (file is NOT created
      yet — it will only be written when the user chooses Save & Exit).
    - If the JSON is corrupted, print a warning and return empty data without
      overwriting the original file.
    - Adds a UUID 'id' to any record that lacks one (backward compat).
    """
    if not os.path.exists(path):
        return _empty_schema()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[Warning] {path} contains invalid JSON: {e}")
        print("[Warning] Starting with empty data. Original file is safe until you Save & Exit.")
        return _empty_schema()
    except OSError as e:
        print(f"[Warning] Could not read {path}: {e}")
        print("[Warning] Starting with empty data.")
        return _empty_schema()

    # Sanity check: required top-level keys must exist.
    if "records" not in data or "meta" not in data:
        print("[Warning] Unrecognised file format. Starting with empty data.")
        return _empty_schema()

    # Backward compat: assign IDs to old records that lack them.
    data["records"] = _ensure_ids(data["records"])

    # Backward compat: 舊的 JSON 檔案沒有 "templates" 欄位，
    # setdefault 的意思是：如果 key 不存在，就自動補上預設值（空清單）。
    # 如果已經有了，就不動它。這樣舊資料升級後不會壞掉。
    data.setdefault("templates", [])

    return data


def save_data(data: dict, path: str = DEFAULT_DATA_FILE) -> None:
    """
    Atomically save *data* to *path*.

    Steps:
      1. Create backups/ copy of the existing file (if it exists).
      2. Write JSON to a temporary file in the same directory as *path*.
      3. Use os.replace() to swap the temp file into place.
         This is atomic on all major OS/filesystems — the original file is
         never partially overwritten.

    Note: meta.updated_at should be set by the caller BEFORE calling this
    function (see action_save_exit in main.py).
    """
    # Step 1 — backup the old file.
    _create_backup(path)

    # Step 2 — write to a temp file in the same directory so os.replace works.
    data_dir = os.path.dirname(os.path.abspath(path))
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            # If writing fails, clean up the half-written temp file.
            os.unlink(tmp_path)
            raise

        # Step 3 — atomic swap.
        os.replace(tmp_path, path)

    except OSError as e:
        print(f"[Error] Could not save data: {e}")
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Validation helpers — "add" variants (blank → sensible default or error)
# ---------------------------------------------------------------------------

def validate_date(raw: str) -> str:
    """
    For ADD: blank input defaults to today's date.
    Shorthand: 1-2 digit input (e.g. "9" or "10") fills in current year and month.
    Full input must be in YYYY-MM-DD format.
    Raises ValueError on bad format.
    """
    raw = raw.strip()
    if raw == "":
        return date.today().isoformat()
    # 只輸入日期數字（1~31）→ 自動補上今年今月
    if raw.isdigit() and 1 <= int(raw) <= 31:
        today = date.today()
        try:
            return date(today.year, today.month, int(raw)).isoformat()
        except ValueError:
            raise ValueError(f"Day {raw} is not valid for {today.strftime('%B %Y')}.")
    parsed = datetime.strptime(raw, "%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def validate_exercise(raw: str) -> str:
    """Return stripped exercise name, or raise ValueError if empty."""
    name = raw.strip()
    if not name:
        raise ValueError("Exercise name cannot be empty.")
    return name


def validate_positive_int(raw: str, field: str) -> int:
    """Parse a positive integer. Raise ValueError with a friendly message on failure."""
    raw = raw.strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f"{field} must be a positive whole number (e.g. 3).")
    return int(raw)


def validate_weight(raw: str) -> float:
    """Parse a float >= 0. Raise ValueError on bad input."""
    raw = raw.strip()
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("Weight must be a number (e.g. 60 or 62.5).")
    if value < 0:
        raise ValueError("Weight cannot be negative.")
    return value


# ---------------------------------------------------------------------------
# Validation helpers — "edit" variants (blank → keep old value, no error)
# ---------------------------------------------------------------------------

def validate_date_edit(raw: str, old_value: str) -> str:
    """
    For EDIT: blank input keeps *old_value* unchanged.
    Shorthand: 1-2 digit input fills in current year and month (same as validate_date).
    Full input must be YYYY-MM-DD. Raises ValueError on bad format.
    """
    raw = raw.strip()
    if raw == "":
        return old_value
    if raw.isdigit() and 1 <= int(raw) <= 31:
        today = date.today()
        try:
            return date(today.year, today.month, int(raw)).isoformat()
        except ValueError:
            raise ValueError(f"Day {raw} is not valid for {today.strftime('%B %Y')}.")
    parsed = datetime.strptime(raw, "%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def validate_exercise_edit(raw: str, old_value: str) -> str:
    """For EDIT: blank keeps *old_value*. Non-blank must be non-empty string."""
    raw = raw.strip()
    if raw == "":
        return old_value
    return validate_exercise(raw)


def validate_positive_int_edit(raw: str, field: str, old_value: int) -> int:
    """For EDIT: blank keeps *old_value*. Non-blank must be a positive integer."""
    raw = raw.strip()
    if raw == "":
        return old_value
    return validate_positive_int(raw, field)


def validate_weight_edit(raw: str, old_value: float) -> float:
    """For EDIT: blank keeps *old_value*. Non-blank must be a float >= 0."""
    raw = raw.strip()
    if raw == "":
        return old_value
    return validate_weight(raw)


# ---------------------------------------------------------------------------
# Record factory
# ---------------------------------------------------------------------------

def make_record(
    exercise: str,
    sets: int,
    reps: int,
    weight: float,
    record_date: str,
    note: str = "",
    template: str = "",    # 記錄這筆資料是從哪個模板建立的（選填）
    session_id: str = "",  # 同一次訓練的所有動作共用同一個 session_id（選填）
) -> dict:
    """Package validated fields into a new record dict with a fresh UUID."""
    return {
        "id": str(uuid.uuid4()),
        "date": record_date,
        "exercise": exercise,
        "sets": sets,
        "reps": reps,
        "weight": weight,
        "note": note,
        "template": template,
        # session_id：從模板一次新增的動作共用同一個值，方便識別「同一次訓練」
        # 空字串代表手動新增（舊資料相容）
        "session_id": session_id,
    }


def find_record_by_id(records: list[dict], record_id: str) -> Optional[dict]:
    """Return the first record whose 'id' matches *record_id*, or None."""
    for rec in records:
        if rec.get("id") == record_id:
            return rec
    return None


# ---------------------------------------------------------------------------
# Export / summary helpers
# ---------------------------------------------------------------------------

def build_summary(records: list[dict]) -> dict:
    """
    Compute per-exercise statistics from *records*.

    Returns a dict with:
      - generated_at (ISO timestamp)
      - total_records (int)
      - unique_exercises (int)
      - exercises (list of per-exercise stat dicts)

    Each exercise dict contains:
      exercise, sessions, max_weight, avg_weight, total_volume, last_date
    """
    # Group records by lowercased exercise name.
    groups: dict[str, list[dict]] = {}
    for r in records:
        key = r["exercise"].lower()
        groups.setdefault(key, []).append(r)

    exercises = []
    for key in sorted(groups):
        recs = groups[key]
        display_name = recs[-1]["exercise"]  # preserve latest casing
        weights = [r["weight"] for r in recs]
        # Volume = sets * reps * weight per session, then summed.
        volumes = [r["sets"] * r["reps"] * r["weight"] for r in recs]

        # Sessions = distinct session_ids (template workouts) +
        #            individual records without a session_id (manually added).
        sids = [r.get("session_id", "") for r in recs]
        sessions = len({s for s in sids if s}) + sum(1 for s in sids if not s)

        exercises.append({
            "exercise": display_name,
            "sessions": sessions,
            "max_weight": max(weights),
            "avg_weight": round(mean(weights), 2),
            "total_volume": round(sum(volumes), 2),
            "last_date": max(r["date"] for r in recs),
        })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_records": len(records),
        "unique_exercises": len(groups),
        "exercises": exercises,
    }


def export_summary_txt(summary: dict, path: str = "summary.txt") -> None:
    """Write a human-readable plain-text summary to *path*."""
    lines = [
        "=" * 76,
        "  TRAINING SUMMARY",
        f"  Generated : {summary['generated_at']}",
        "=" * 76,
        f"  Total records   : {summary['total_records']}",
        f"  Unique exercises: {summary['unique_exercises']}",
        "",
        (
            f"  {'EXERCISE':<24} {'SESSIONS':>8} {'MAX(kg)':>8} "
            f"{'AVG(kg)':>8} {'VOLUME':>12} {'LAST DATE':>12}"
        ),
        "  " + "-" * 74,
    ]
    for ex in summary["exercises"]:
        lines.append(
            f"  {ex['exercise']:<24} {ex['sessions']:>8} "
            f"{ex['max_weight']:>8.2f} {ex['avg_weight']:>8.2f} "
            f"{ex['total_volume']:>12.2f} {ex['last_date']:>12}"
        )
    lines += ["=" * 76, ""]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_summary_json(summary: dict, path: str = "summary.json") -> None:
    """Write the summary dict as machine-readable JSON to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
