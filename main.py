"""
main.py — Gym Training Logger CLI entry point  (v1.1)

Run:
  python main.py                        # uses training.json in current directory
  python main.py --file my_log.json     # uses a custom data file

Menu:
  1) Add workout from template
  2) Show last records (edit/delete inline)
  3) Search records
  4) Generate suggestions
  5) Show chart
  9) Manage templates
  0) Save & Exit
"""

import argparse
import atexit
import os
import re
import sys
import uuid
from datetime import date, datetime
from typing import Optional

import storage
import suggest
import database

# ---------------------------------------------------------------------------
# Auto-save safety net
# ---------------------------------------------------------------------------

# Holds a reference to the live data dict and file path so atexit can save.
# 'saved' is set to True by action_save_exit to prevent a redundant second save.
_session: dict = {"data": None, "file": None, "saved": False}


def _atexit_save() -> None:
    """
    Called automatically when the process exits for any reason
    (Ctrl+C, unhandled exception, os._exit excluded).
    Skipped if the user already saved with option 0.
    """
    if _session["saved"] or _session["data"] is None:
        return
    try:
        _session["data"]["meta"]["updated_at"] = datetime.now().isoformat(timespec="seconds")
        storage.save_data(_session["data"], _session["file"])
        print(f"\n  [Auto-saved to {_session['file']}]")
    except Exception:
        pass  # Never raise inside atexit


# ---------------------------------------------------------------------------
# UI constants
# ---------------------------------------------------------------------------

HEADER = """
╔══════════════════════════════════╗
║     GYM TRAINING LOGGER  v1.1   ║
╚══════════════════════════════════╝"""

MENU = """
  1) Add workout from template
  2) Show last records
  3) Search records (by exercise)
  4) Generate suggestions
  5) Show chart
  6) Volume analysis
  7) PR analysis
  8) Training frequency
  9) Manage templates
  0) Save & Exit
"""

# Column widths used in record tables (shared by every table-printing helper).
COL = {
    "date": 12,
    "exercise": 22,
    "sets": 5,
    "reps": 5,
    "weight": 10,
}


# ---------------------------------------------------------------------------
# Low-level display helpers
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 60) -> str:
    """Return a horizontal rule string (indented by two spaces)."""
    return "  " + char * width


def _prompt(label: str, default: str = "") -> str:
    """Show a prompt with an optional [default] hint and return stripped input."""
    hint = f" [{default}]" if default else ""
    return input(f"  {label}{hint}: ").strip()


def _ask(label: str, default: str = "") -> str:
    """Thin wrapper around _prompt — kept separate to make unit-testing easier."""
    return _prompt(label, default)


def _input_with_retry(label: str, validator, default: str = "") -> any:
    """
    Repeatedly prompt the user until validator(raw_input) succeeds.

    validator must either return the cleaned value or raise ValueError.
    Returns the first successfully validated value.
    """
    while True:
        raw = _ask(label, default)
        effective = default if (not raw and default) else raw
        try:
            return validator(effective)
        except ValueError as e:
            print(f"  [!] {e}  — please try again.")


def _print_record_table(records: list[dict], numbered: bool = False) -> None:
    """
    Print a formatted table of records to stdout.

    If *numbered* is True, prepend a 1-based index column so the user
    can reference rows by number (used in Edit/Delete flows).
    """
    prefix_header = f"  {'#':>3}  " if numbered else "  "
    print(
        prefix_header
        + f"{'DATE':<{COL['date']}} {'EXERCISE':<{COL['exercise']}} "
        f"{'SETS':>{COL['sets']}} {'REPS':>{COL['reps']}} "
        f"{'WEIGHT(kg)':>{COL['weight']}}  NOTE"
    )
    print(_hr())
    for i, r in enumerate(records, 1):
        note_short = (r["note"][:18] + "…") if len(r["note"]) > 18 else r["note"]
        prefix = f"  {i:>3}  " if numbered else "  "
        print(
            prefix
            + f"{r['date']:<{COL['date']}} {r['exercise']:<{COL['exercise']}} "
            f"{r['sets']:>{COL['sets']}} {r['reps']:>{COL['reps']}} "
            f"{r['weight']:>{COL['weight']}.2f}  {note_short}"
        )


# ---------------------------------------------------------------------------
# Menu action functions
# ---------------------------------------------------------------------------


def action_show_last(data: dict, data_file: str) -> None:
    """Display all records (newest first), then optionally edit or delete one."""
    recent = database.get_all_workouts()  # 從 SQLite 讀，已按日期新→舊排序
    if not recent:
        print("\n  No records yet. Add your first session!")
        return

    print("\n" + _hr())
    print(f"  ALL {len(recent)} RECORDS  (newest first)")
    print(_hr())

    # 印出表頭
    print(
        f"  {'#':>3}  "
        f"{'DATE':<{COL['date']}} {'EXERCISE':<{COL['exercise']}} "
        f"{'SETS':>{COL['sets']}} {'REPS':>{COL['reps']}} "
        f"{'WEIGHT(kg)':>{COL['weight']}}  NOTE"
    )
    print(_hr())

    # 逐筆印出，遇到新 session_id 時先印一條分組標題
    seen_sessions: set = set()
    for i, rec in enumerate(recent, 1):
        sid = rec.get("session_id", "")
        if sid and sid not in seen_sessions:
            seen_sessions.add(sid)
            tmpl = rec.get("template", "")
            header = f"  ·· {rec['date']}  {tmpl} "
            print(header + "·" * max(0, 58 - len(header)))

        note_short = (rec["note"][:18] + "…") if len(rec["note"]) > 18 else rec["note"]
        print(
            f"  {i:>3}  "
            f"{rec['date']:<{COL['date']}} {rec['exercise']:<{COL['exercise']}} "
            f"{rec['sets']:>{COL['sets']}} {rec['reps']:>{COL['reps']}} "
            f"{rec['weight']:>{COL['weight']}.2f}  {note_short}"
        )

    print(_hr())

    # ── 選擇要操作的紀錄 ──────────────────────────────────────
    raw = input("\n  Row number to edit/delete (Enter to skip): ").strip()
    if not raw:
        return
    try:
        idx = int(raw)
        if not (1 <= idx <= len(recent)):
            print(f"  [!] Please enter a number between 1 and {len(recent)}.")
            return
    except ValueError:
        print("  [!] Please enter a number.")
        return

    rec = recent[idx - 1]   # dict from SQLite — id is an integer

    action = input("  (e) Edit   (d) Delete   (0) Cancel: ").strip().lower()

    if action == "e":
        print(f"\n  Editing — press Enter on any field to keep current value.")
        print(_hr())
        rec["date"] = _input_with_retry(
            "Date", lambda r: storage.validate_date_edit(r, rec["date"]),
            default=rec["date"],
        )
        rec["exercise"] = _input_with_retry(
            "Exercise", lambda r: storage.validate_exercise_edit(r, rec["exercise"]),
            default=rec["exercise"],
        )
        rec["sets"] = _input_with_retry(
            "Sets", lambda r: storage.validate_positive_int_edit(r, "Sets", rec["sets"]),
            default=str(rec["sets"]),
        )
        rec["reps"] = _input_with_retry(
            "Reps per set", lambda r: storage.validate_positive_int_edit(r, "Reps", rec["reps"]),
            default=str(rec["reps"]),
        )
        rec["weight"] = _input_with_retry(
            "Weight (kg)", lambda r: storage.validate_weight_edit(r, rec["weight"]),
            default=str(rec["weight"]),
        )
        note_raw = _ask("Note (Enter to keep current)", default=rec["note"])
        if note_raw:
            rec["note"] = note_raw
        # 把改好的資料寫回 SQLite
        database.update_workout(
            rec["id"],
            date=rec["date"], exercise=rec["exercise"],
            sets=rec["sets"], reps=rec["reps"],
            weight=rec["weight"], notes=rec["note"],
        )
        print(f"\n  ✔ Updated: {rec['exercise']} — {rec['sets']}×{rec['reps']} @ {rec['weight']} kg on {rec['date']}")

    elif action == "d":
        print(f"\n  About to delete: {rec['date']}  {rec['exercise']}  {rec['sets']}×{rec['reps']} @ {rec['weight']} kg")
        if rec["note"]:
            print(f"  Note: {rec['note']}")
        if input("\n  Are you sure? (y/n): ").strip().lower() == "y":
            database.delete_workout(rec["id"])  # 從 SQLite 刪除
            print("  ✔ Record deleted.")
        else:
            print("  Cancelled.")


def action_search(data: dict, data_file: str) -> None:
    """Search records by exercise keyword (case-insensitive)."""
    records = database.get_all_workouts()  # 從 SQLite 讀
    if not records:
        print("\n  No records yet.")
        return

    keyword = _ask("Search keyword (exercise name)").lower()
    if not keyword:
        print("  [!] Please enter a keyword.")
        return

    matches = [r for r in records if keyword in r["exercise"].lower()]
    if not matches:
        print(f"\n  No records found for '{keyword}'.")
        return

    print(f"\n  Found {len(matches)} record(s) matching '{keyword}':")
    print(_hr())
    _print_record_table(matches)
    print(_hr())


def action_volume(data: dict, data_file: str) -> None:
    """顯示每個動作的總訓練量（volume = weight × reps × sets），由大到小排序。"""
    rows = database.get_total_volume_by_exercise()

    print("\n" + _hr())
    print("  VOLUME ANALYSIS  (weight × reps × sets)")
    print(_hr())

    if not rows:
        print("  No records yet.")
        print(_hr())
        return

    # 找最大 volume，用來畫比例長條
    max_vol = rows[0][1]

    print(f"  {'EXERCISE':<25} {'TOTAL VOLUME (kg)':>18}  BAR")
    print("  " + "-" * 60)

    for exercise, total_vol in rows:
        # 長條圖最長 20 格，按比例縮放
        bar_len = int((total_vol / max_vol) * 20)
        bar = "█" * bar_len
        print(f"  {exercise:<25} {total_vol:>16,.1f}  {bar}")

    print(_hr())


def action_pr(data: dict, data_file: str) -> None:
    """顯示每個動作的 PR（Personal Record = 最大重量），由重到輕排序。"""
    rows = database.get_pr_by_exercise()

    print("\n" + _hr())
    print("  PERSONAL RECORDS  (max weight per exercise)")
    print(_hr())

    if not rows:
        print("  No records yet.")
        print(_hr())
        return

    print(f"  {'EXERCISE':<25} {'PR (kg)':>10}")
    print("  " + "-" * 38)

    for exercise, pr in rows:
        print(f"  {exercise:<25} {pr:>10.2f}")

    print(_hr())


def action_frequency(data: dict, data_file: str) -> None:
    """顯示每個動作的訓練次數（共有幾筆紀錄），由多到少排序。"""
    rows = database.get_training_frequency()

    print("\n" + _hr())
    print("  TRAINING FREQUENCY  (sessions per exercise)")
    print(_hr())

    if not rows:
        print("  No records yet.")
        print(_hr())
        return

    print(f"  {'EXERCISE':<25} {'COUNT':>8}")
    print("  " + "-" * 36)

    for exercise, freq in rows:
        print(f"  {exercise:<25} {freq:>8}")

    print(_hr())


def action_suggestions(data: dict, data_file: str) -> None:
    """Generate and display progressive overload suggestions."""
    print("\n" + _hr())
    print("  PROGRESSIVE OVERLOAD SUGGESTIONS")
    print(_hr())
    suggestions = suggest.generate_suggestions(database.get_all_workouts())  # 從 SQLite 讀
    suggest.print_suggestions(suggestions)
    print(_hr())


def _draw_ascii_chart(title: str, dates: list, weights: list) -> None:
    """
    在終端機畫一個 ASCII 折線圖。

    輸入：
      title   - 圖表標題
      dates   - 日期字串清單，例如 ["2026-03-05", "2026-03-08"]
      weights - 對應的重量清單，例如 [60.0, 62.5]

    輸出：直接 print 到螢幕，不回傳任何值
    """
    HEIGHT = 10    # 圖表的高度（幾行）
    COL_W  = 9     # 每個資料點佔幾個字元寬（用來對齊 x 軸日期）

    # 計算 Y 軸的範圍，加 10% 上下留白，讓點不會貼在邊框上
    min_w   = min(weights)
    max_w   = max(weights)
    w_range = max_w - min_w if max_w != min_w else 1.0
    y_min   = min_w - w_range * 0.10
    y_max   = max_w + w_range * 0.10
    y_range = y_max - y_min

    # 建立一個二維網格（HEIGHT 行 × len(dates) 列），預設全部空白
    grid = [[" " for _ in dates] for _ in range(HEIGHT)]

    # 把每個資料點放到對應的格子裡
    for col, w in enumerate(weights):
        # normalized = 0.0 代表最底部，1.0 代表最頂部
        normalized = (w - y_min) / y_range
        # row 0 在最上面（最高重量），所以要反轉
        row = HEIGHT - 1 - round(normalized * (HEIGHT - 1))
        row = max(0, min(HEIGHT - 1, row))   # 確保不超出邊界
        grid[row][col] = "●"                 # 放上資料點符號

    # ── 印出圖表 ──────────────────────────────────────────────
    print(f"\n  {title}")
    print()

    # 逐行印出（每行左邊是 Y 軸數值標籤）
    for row_idx, row in enumerate(grid):
        # 計算這一行對應的重量值（從 y_max 往下遞減）
        y_val = y_max - (row_idx / max(HEIGHT - 1, 1)) * y_range
        y_label = f"  {y_val:6.1f} │"
        # 每個格子置中在 COL_W 寬度內
        cells = "".join(cell.center(COL_W) for cell in row)
        print(y_label + cells)

    # 底部邊框線
    print("         └" + "─" * (COL_W * len(dates)))

    # X 軸日期標籤（只顯示 MM-DD 部分，節省空間）
    date_row = "          " + "".join(d[5:].center(COL_W) for d in dates)
    print(date_row)
    print()


def action_show_chart(data: dict, data_file: str) -> None:
    """
    讓使用者選一個動作，用 ASCII 折線圖顯示該動作的重量趨勢。

    流程：
      1. 列出所有有紀錄的動作
      2. 使用者選擇一個
      3. 同一天有多筆時，取當天最大重量（代表最佳表現）
      4. 呼叫 _draw_ascii_chart() 畫圖
      5. 顯示最小/最大/筆數摘要
    """
    records = database.get_all_workouts()  # 從 SQLite 讀

    if not records:
        print("\n  No records yet. Add some sessions first!")
        return

    # ── 步驟 1：收集所有動作名稱（不分大小寫去重）────────────
    # exercise_map = {小寫名稱: 顯示名稱}
    # 同一個動作可能有不同大小寫，用最後出現的那個當顯示名稱
    exercise_map = {}
    for r in records:
        exercise_map[r["exercise"].lower()] = r["exercise"]

    exercises = sorted(exercise_map.keys())   # 按字母排序

    print("\n" + _hr())
    print("  SHOW CHART")
    print(_hr())
    print("\n  Available exercises:")
    for i, key in enumerate(exercises, 1):
        print(f"    {i}) {exercise_map[key]}")
    print()

    # ── 步驟 2：讓使用者選擇動作 ────────────────────────────
    while True:
        raw = input("  Choose an exercise number (0 to cancel): ").strip()
        if raw == "0":
            print("  Cancelled.")
            return
        try:
            idx = int(raw)
            if 1 <= idx <= len(exercises):
                chosen_key  = exercises[idx - 1]
                chosen_name = exercise_map[chosen_key]
                break
            print(f"  [!] Please enter a number between 1 and {len(exercises)}.")
        except ValueError:
            print("  [!] Please enter a number.")

    # ── 步驟 3：篩選並整理資料 ───────────────────────────────
    # 取出該動作所有紀錄，按日期排序
    recs = sorted(
        [r for r in records if r["exercise"].lower() == chosen_key],
        key=lambda r: r["date"],
    )

    # 至少需要 2 個資料點才能畫趨勢線
    if len(recs) < 2:
        print(f"\n  '{chosen_name}' only has {len(recs)} record(s).")
        print("  Need at least 2 records to draw a trend chart.")
        return

    # 同一天有多筆時，取最大重量（當天最佳表現）
    date_weight: dict[str, float] = {}
    for r in recs:
        d = r["date"]
        date_weight[d] = max(date_weight.get(d, 0.0), r["weight"])

    dates   = sorted(date_weight.keys())
    weights = [date_weight[d] for d in dates]

    # 如果資料點太多，只取最近 20 筆，圖表比較好看
    MAX_POINTS = 20
    if len(dates) > MAX_POINTS:
        dates   = dates[-MAX_POINTS:]
        weights = weights[-MAX_POINTS:]
        print(f"\n  (Showing last {MAX_POINTS} sessions only)")

    # ── 步驟 4：畫圖 ─────────────────────────────────────────
    _draw_ascii_chart(
        title   = f"{chosen_name}  — weight trend (max per day, kg)",
        dates   = dates,
        weights = weights,
    )

    # ── 步驟 5：摘要數字 ─────────────────────────────────────
    print(f"  Min: {min(weights):.2f} kg   Max: {max(weights):.2f} kg   "
          f"Sessions plotted: {len(dates)}")
    print(_hr())


def _extract_suggested_weight(sugg: dict) -> Optional[float]:
    """Extract a numeric weight from a suggestion dict for use as a default."""
    # "Increase to 122.50 kg" or "Deload to 110.00 kg"
    m = re.search(r"to ([\d.]+) kg", sugg.get("suggestion", ""))
    if m:
        return float(m.group(1))
    # "Maintain current weight" — pull last session weight from reason text
    m = re.search(r"@ ([\d.]+) kg", sugg.get("reason", ""))
    if m:
        return float(m.group(1))
    return None


def _ask_weight_or_skip(weight_default: str) -> Optional[float]:
    """
    Prompt for weight; return float on valid input, None if user types 's' to skip.
    Retries on invalid input (same pattern as _input_with_retry).
    """
    hint = f" [{weight_default}]" if weight_default else ""
    while True:
        raw = input(f"  Weight (kg){hint} (s=skip): ").strip()
        if raw.lower() == "s":
            return None
        effective = weight_default if (not raw and weight_default) else raw
        try:
            return storage.validate_weight(effective)
        except ValueError as e:
            print(f"  [!] {e}  — please try again.")


def _parse_sets_reps(raw: str, default_sets: int, default_reps: int) -> tuple:
    """Parse 'N N' input; return (default_sets, default_reps) on empty input."""
    if not raw.strip():
        return default_sets, default_reps
    parts = raw.strip().split()
    if len(parts) != 2:
        raise ValueError("Enter two numbers separated by a space, e.g. 3 8.")
    s = storage.validate_positive_int(parts[0], "Sets")
    r = storage.validate_positive_int(parts[1], "Reps")
    return s, r


def action_add_from_template(data: dict, data_file: str) -> None:
    """
    讓使用者選一個訓練模板，輸入一次日期，
    然後依序為每個動作輸入重量，批次建立訓練紀錄。
    """
    print("\n" + _hr())
    print("  ADD WORKOUT FROM TEMPLATE")
    print(_hr())

    templates = data["templates"]   # 取出所有模板（是一個 list）

    # 如果沒有任何模板，提示使用者並返回
    if not templates:
        print("\n  No templates found.")
        print("  Tip: add a template directly in training.json under \"templates\".")
        print("  Example:")
        print('    {"name": "Push Day", "items": [')
        print('      {"exercise": "Bench Press", "sets": 3, "reps": 8, "note": ""}')
        print('    ]}')
        return

    # 顯示所有模板的編號和名稱，讓使用者選擇
    print("\n  Available templates:")
    for i, tmpl in enumerate(templates, 1):
        # 計算這個模板有幾個動作，顯示在後面
        item_count = len(tmpl["items"])
        print(f"    {i}) {tmpl['name']}  ({item_count} exercise(s))")

    print()

    # 讓使用者輸入模板編號，不斷重試直到輸入正確
    while True:
        raw = input("  Choose a template number (0 to cancel): ").strip()
        if raw == "0":
            print("  Cancelled.")
            return
        try:
            idx = int(raw)                          # 把字串轉成整數
            if 1 <= idx <= len(templates):          # 確認編號在範圍內
                chosen = templates[idx - 1]         # 取出對應的模板（清單從 0 開始，所以 -1）
                break                               # 輸入正確，跳出 while 迴圈
            print(f"  [!] Please enter a number between 1 and {len(templates)}.")
        except ValueError:
            print("  [!] Please enter a number.")

    # 顯示使用者選到的模板名稱
    print(f"\n  Template: {chosen['name']}")
    print(_hr())

    # 詢問這次訓練的日期（整個模板只問一次，全部動作共用同一天）
    today = date.today().isoformat()
    record_date = _input_with_retry(
        "Workout date (YYYY-MM-DD, blank = today)",
        storage.validate_date,
        default=today,
    )

    print(f"\n  Now enter the weight for each exercise on {record_date}:")
    print(_hr())

    added = []   # 用來收集這次新增的所有紀錄，最後統一加入 data["records"]

    # 這次訓練的所有動作共用同一個 session_id，讓它們可以被識別為「同一次訓練」
    session_id = str(uuid.uuid4())

    # 事先算好每個動作的建議重量，建成 {動作名稱小寫: 建議dict} 查詢表
    sugg_map = {s["exercise"].lower(): s for s in suggest.generate_suggestions(database.get_all_workouts())}  # 從 SQLite 讀

    # 逐一處理模板裡的每個動作
    for item in chosen["items"]:
        exercise = item["exercise"]   # 動作名稱
        sets     = item["sets"]       # 組數（從模板來，不用重新輸入）
        reps     = item["reps"]       # 次數（同上）
        note     = item.get("note", "")  # 備註（選填，模板裡可能沒有這個 key，所以用 .get()）

        # 顯示這個動作的基本資訊
        print(f"\n  → {exercise}  ({sets} sets × {reps} reps)")

        # 取建議重量作為預設值（有歷史才顯示）
        sugg = sugg_map.get(exercise.lower())
        weight_default = ""
        if sugg:
            sw = _extract_suggested_weight(sugg)
            if sw is not None:
                weight_default = f"{sw:.2f}"

        # 問重量（輸入 s 可跳過此動作）
        weight = _ask_weight_or_skip(weight_default)
        if weight is None:
            print("  ↳ Skipped.")
            continue

        # 問實際完成的 sets × reps（單行 N N 格式，Enter = 模板目標）
        actual_sets, actual_reps = _input_with_retry(
            "Actual (sets reps)",
            lambda raw, s=sets, r=reps: _parse_sets_reps(raw, s, r),
            default=f"{sets} {reps}",
        )

        record = storage.make_record(
            exercise, actual_sets, actual_reps, weight, record_date,
            note=note,
            template=chosen["name"],
            session_id=session_id,
        )
        added.append(record)   # 先收集起來

    # ── 追加額外動作 ──────────────────────────────────────────
    print("\n" + _hr("·"))
    while input("  Any extra exercises? (y/n): ").strip().lower() == "y":
        exercise = _input_with_retry("  Exercise name", storage.validate_exercise)

        sugg = sugg_map.get(exercise.lower())
        weight_default = ""
        if sugg:
            sw = _extract_suggested_weight(sugg)
            if sw is not None:
                weight_default = f"{sw:.2f}"

        weight = _input_with_retry("  Weight (kg)", storage.validate_weight, default=weight_default)

        extra_sets, extra_reps = _input_with_retry(
            "  Actual (sets reps)",
            lambda raw, s=1, r=1: _parse_sets_reps(raw, s, r),
        )

        record = storage.make_record(
            exercise, extra_sets, extra_reps, weight, record_date,
            template=chosen["name"], session_id=session_id,
        )
        added.append(record)
        print(f"  ✔ Added: {exercise}  {extra_sets}×{extra_reps} @ {weight} kg")

    # 把所有新紀錄加入 data["records"]
    data["records"].extend(added)

    # 同步寫入 SQLite（JSON 流程保持不變）
    database.init_db()
    for rec in added:
        database.add_workout(
            date=rec["date"],
            exercise=rec["exercise"],
            weight=rec["weight"],
            sets=rec["sets"],
            reps=rec["reps"],
            notes=rec.get("note", ""),
        )

    # 顯示完成訊息，提醒使用者還要選 0 才會存檔
    print("\n" + _hr())
    print(f"  ✔ {len(added)} record(s) added from template '{chosen['name']}' on {record_date}.")
    print("  Remember to choose 0 to save!")


def _action_add_template(data: dict) -> None:
    """
    【子功能】讓使用者輸入一個新的訓練模板，並存入 data["templates"]。

    流程：
      1. 輸入模板名稱
      2. 逐一輸入動作（exercise、sets、reps、note）
      3. 每加完一個動作，問是否繼續新增
      4. 完成後把整個模板加入清單
    """
    print("\n" + _hr())
    print("  ADD NEW TEMPLATE")
    print(_hr())

    # ── 步驟 1：輸入模板名稱 ──────────────────────────────────
    # 取得已有的模板名稱清單（全部轉小寫），用來防止重複命名
    existing_names = [t["name"].lower() for t in data["templates"]]

    while True:
        name = _ask("Template name").strip()
        if not name:
            print("  [!] Template name cannot be empty.")
        elif name.lower() in existing_names:
            # 名稱已存在（不分大小寫）
            print(f"  [!] A template named '{name}' already exists.")
        else:
            break   # 名稱合法，跳出迴圈

    # ── 步驟 2：逐一輸入動作 ──────────────────────────────────
    items = []   # 收集這個模板的所有動作

    print(f"\n  Adding exercises to '{name}'. Enter at least one.")
    print("  (You will be asked after each exercise if you want to add another.)")

    while True:
        print(f"\n  Exercise #{len(items) + 1}")
        print(_hr("·", 40))

        # 動作名稱（不能空白）
        exercise = _input_with_retry("  Exercise name", storage.validate_exercise)

        # 組數（必須是正整數）
        sets = _input_with_retry(
            "  Sets",
            lambda raw: storage.validate_positive_int(raw, "Sets"),
        )

        # 次數（必須是正整數）
        reps = _input_with_retry(
            "  Reps per set",
            lambda raw: storage.validate_positive_int(raw, "Reps"),
        )

        # 備註（選填，直接 Enter 就是空字串）
        note = _ask("  Note (optional)").strip()

        # 把這個動作包裝成 dict 加入清單
        items.append({
            "exercise": exercise,
            "sets": sets,
            "reps": reps,
            "note": note,
        })

        # 問使用者是否繼續新增動作
        more = input("\n  Add another exercise? (y/n): ").strip().lower()
        if more != "y":
            break   # 使用者不想繼續，跳出迴圈

    # ── 步驟 3：把完整模板加入 data["templates"] ──────────────
    new_template = {
        "name": name,
        "items": items,
    }
    data["templates"].append(new_template)

    print(f"\n  ✔ Template '{name}' created with {len(items)} exercise(s).")
    print("  Remember to choose 0 to save!")


def _action_delete_template(data: dict) -> None:
    """
    【子功能】讓使用者選一個模板並刪除它（需確認）。
    """
    print("\n" + _hr())
    print("  DELETE TEMPLATE")
    print(_hr())

    templates = data["templates"]

    # 如果沒有任何模板，直接返回
    if not templates:
        print("\n  No templates to delete.")
        return

    # 顯示所有模板讓使用者選擇
    print("\n  Current templates:")
    for i, tmpl in enumerate(templates, 1):
        print(f"    {i}) {tmpl['name']}  ({len(tmpl['items'])} exercise(s))")

    print()

    # 讓使用者輸入編號，不斷重試直到正確
    while True:
        raw = input("  Choose template to delete (0 to cancel): ").strip()
        if raw == "0":
            print("  Cancelled.")
            return
        try:
            idx = int(raw)
            if 1 <= idx <= len(templates):
                chosen = templates[idx - 1]
                break
            print(f"  [!] Please enter a number between 1 and {len(templates)}.")
        except ValueError:
            print("  [!] Please enter a number.")

    # 顯示將要刪除的模板，要求確認
    print(f"\n  You are about to delete template: '{chosen['name']}'")
    print(f"  It contains {len(chosen['items'])} exercise(s):")
    for item in chosen["items"]:
        print(f"    - {item['exercise']}  {item['sets']}×{item['reps']}")

    confirm = input("\n  Are you sure? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Cancelled — template was NOT deleted.")
        return

    # 用名稱過濾掉被選中的模板（同 delete record 用 ID 過濾的邏輯）
    data["templates"] = [t for t in templates if t["name"] != chosen["name"]]
    print(f"  ✔ Template '{chosen['name']}' deleted.")
    print("  Remember to choose 0 to save!")


def _action_edit_schedule(data: dict, data_file: str) -> None:
    """
    【子功能】讓使用者設定每週哪幾天要訓練、對應哪個模板。
    修改完後立刻存檔，這樣 notify.py 排程執行時能讀到最新設定。
    """
    print("\n" + _hr())
    print("  EDIT SCHEDULE")
    print(_hr())

    templates = data["templates"]
    if not templates:
        print("\n  No templates found. Please add a template first (option 2).")
        return

    # 確保 schedule key 存在
    data.setdefault("schedule", {})
    schedule = data["schedule"]

    DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    while True:
        # 每次迴圈開始都重新顯示最新課表
        print("\n  Current schedule:")
        for i, day in enumerate(DAYS, 1):
            val = schedule.get(day)
            label = val if val else "(rest day)"
            print(f"    {i}) {day.capitalize():<12} → {label}")
        print("    0) Done")
        print()

        # 選擇要編輯哪一天
        raw = input("  Choose a day to edit (0 to finish): ").strip()
        if raw == "0":
            break
        try:
            idx = int(raw)
            if not (1 <= idx <= len(DAYS)):
                print(f"  [!] Please enter a number between 1 and {len(DAYS)}.")
                continue
        except ValueError:
            print("  [!] Please enter a number.")
            continue

        chosen_day = DAYS[idx - 1]

        # 選擇模板
        print(f"\n  Set template for {chosen_day.capitalize()}:")
        for i, tmpl in enumerate(templates, 1):
            print(f"    {i}) {tmpl['name']}")
        print("    0) Clear (make it a rest day)")
        print()

        while True:
            raw = input("  Choose a template (0 to clear): ").strip()
            try:
                idx = int(raw)
                if idx == 0:
                    schedule.pop(chosen_day, None)
                    print(f"  ✔ {chosen_day.capitalize()} → rest day")
                    break
                elif 1 <= idx <= len(templates):
                    schedule[chosen_day] = templates[idx - 1]["name"]
                    print(f"  ✔ {chosen_day.capitalize()} → {schedule[chosen_day]}")
                    break
                print(f"  [!] Please enter a number between 0 and {len(templates)}.")
            except ValueError:
                print("  [!] Please enter a number.")

    # 立刻存檔，讓 notify.py 能讀到最新課表
    data["meta"]["updated_at"] = datetime.now().isoformat(timespec="seconds")
    storage.save_data(data, data_file)
    print("  ✔ Schedule saved.")


def action_manage_templates(data: dict, data_file: str) -> None:
    """
    模板管理的主選單。
    讓使用者在這裡新增或刪除模板，輸入 0 回到上層選單。
    """
    # 子選單文字（8 的功能移到這裡變成選項 1）
    SUB_MENU = """
  MANAGE TEMPLATES
  ─────────────────────────────────
  1) Add new template
  2) Delete template
  3) Edit schedule
  0) Back to main menu
"""
    while True:
        count = len(data["templates"])
        print(f"\n  (You have {count} template(s))")
        print(SUB_MENU)

        choice = input("  Your choice: ").strip()

        if choice == "1":
            _action_add_template(data)
        elif choice == "2":
            _action_delete_template(data)
        elif choice == "3":
            _action_edit_schedule(data, data_file)
        elif choice == "0":
            return
        else:
            print("  [!] Please enter 0, 1, 2, or 3.")


def action_save_exit(data: dict, data_file: str) -> None:
    """
    Set meta.updated_at, atomically save to disk (with backup), then exit.

    meta.updated_at is intentionally updated ONLY here, not on every operation,
    so the timestamp reflects when the user last chose to persist their data.
    """
    data["meta"]["updated_at"] = datetime.now().isoformat(timespec="seconds")
    storage.save_data(data, data_file)
    _session["saved"] = True
    print(f"\n  Data saved to {data_file}. Goodbye, champ!\n")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments. Currently supports --file."""
    parser = argparse.ArgumentParser(
        description="Gym Training Logger v1.1 — track your gym sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py\n"
            "  python main.py --file my_training.json\n"
        ),
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default=storage.DEFAULT_DATA_FILE,
        help=(
            f"Path to the training data JSON file "
            f"(default: {storage.DEFAULT_DATA_FILE})"
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Menu dispatch table
# ---------------------------------------------------------------------------

ACTIONS: dict[str, callable] = {
    "1": action_add_from_template,
    "2": action_show_last,
    "3": action_search,
    "4": action_suggestions,
    "5": action_show_chart,
    "6": action_volume,
    "7": action_pr,
    "8": action_frequency,
    "9": action_manage_templates,
    "0": action_save_exit,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    data_file: str = args.file

    print(HEADER)

    data = storage.load_data(data_file)
    record_count = len(data["records"])
    print(f"\n  Loaded {record_count} record(s) from {data_file}")

    # Register auto-save so data is never lost on Ctrl+C or unexpected crashes.
    _session["data"] = data
    _session["file"] = data_file
    atexit.register(_atexit_save)

    while True:
        print(MENU)
        choice = input("  Your choice: ").strip()

        if choice not in ACTIONS:
            print("  [!] Invalid choice. Please enter a number shown in the menu.")
            continue

        ACTIONS[choice](data, data_file)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted — auto-saving before exit...")
        sys.exit(0)  # triggers atexit → _atexit_save()
