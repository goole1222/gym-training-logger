"""
migrate.py — 把 training.json 的舊紀錄匯入 SQLite

執行方式：
  py migrate.py                          # 使用預設的 training.json 和 training.db
  py migrate.py --json my.json --db my.db   # 指定自訂路徑

重複執行是安全的：
  程式會先用「日期 + 動作名稱 + 重量 + 組數 + 次數」做比對，
  如果 SQLite 裡已經有完全相同的紀錄，就跳過不重複匯入。
"""

import argparse
import json
import os
import sys

import database


def load_json_records(json_path: str) -> list[dict]:
    """
    讀取 training.json，回傳 records 列表。
    如果檔案不存在或格式錯誤，直接印出錯誤並結束程式。
    """
    if not os.path.exists(json_path):
        print(f"  [ERROR] File not found: {json_path}")
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    print(f"  Found {len(records)} record(s) in {json_path}")
    return records


def build_existing_set(db_path: str) -> set[tuple]:
    """
    從 SQLite 讀出所有現有紀錄，建成一個 set 用於快速查重。
    每筆紀錄用 (date, exercise小寫, weight, sets, reps) 這個組合當作唯一識別。
    這樣重跑 migrate.py 時，已存在的紀錄就會被跳過。
    """
    existing = set()
    for row in database.get_all_workouts(db_path):
        key = (
            row["date"],
            row["exercise"].lower(),
            row["weight"],
            row["sets"],
            row["reps"],
        )
        existing.add(key)
    return existing


def migrate(json_path: str, db_path: str) -> None:
    """
    主要的匯入流程：
    1. 初始化 SQLite（表格不存在才建立）
    2. 讀取 JSON records
    3. 查出 SQLite 現有紀錄，建立查重 set
    4. 逐筆比對，新的才匯入，已存在的跳過
    5. 印出匯入結果摘要
    """
    # 步驟 1：確保資料表存在
    database.init_db(db_path)

    # 步驟 2：讀取 JSON
    records = load_json_records(json_path)
    if not records:
        print("  No records to migrate.")
        return

    # 步驟 3：建立查重 set
    existing = build_existing_set(db_path)
    print(f"  SQLite already has {len(existing)} record(s) — will skip duplicates.\n")

    # 步驟 4：逐筆匯入
    imported = 0
    skipped  = 0

    for rec in records:
        key = (
            rec["date"],
            rec["exercise"].lower(),
            rec["weight"],
            rec["sets"],
            rec["reps"],
        )

        if key in existing:
            # 已存在，跳過
            skipped += 1
            continue

        # JSON 的備注欄位是 "note"（單數），database.add_workout 用 notes 參數
        database.add_workout(
            date=rec["date"],
            exercise=rec["exercise"],
            weight=rec["weight"],
            sets=rec["sets"],
            reps=rec["reps"],
            notes=rec.get("note", ""),   # 有些舊紀錄可能沒有 note 欄位
            db_path=db_path,
        )
        imported += 1

        # 把剛加入的 key 放進 set，避免同一次執行中遇到 JSON 內部重複資料
        existing.add(key)

    # 步驟 5：摘要
    print(f"  Imported : {imported} record(s)")
    print(f"  Skipped  : {skipped} record(s)  (already in SQLite)")
    print(f"  Total    : {len(records)} record(s) in JSON")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate training.json records to SQLite.")
    parser.add_argument("--json", default="training.json", metavar="PATH",
                        help="Path to training.json  (default: training.json)")
    parser.add_argument("--db",   default=database.DEFAULT_DB_FILE, metavar="PATH",
                        help=f"Path to SQLite database  (default: {database.DEFAULT_DB_FILE})")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    print(f"=== migrate.py ===")
    print(f"  JSON : {args.json}")
    print(f"  DB   : {args.db}\n")
    migrate(args.json, args.db)
    print("\n=== done ===")
