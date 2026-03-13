"""
database.py — SQLite 版本的資料存取層

這個檔案負責所有和資料庫有關的操作。
目前只有一張 workouts 資料表，對應原本 JSON 裡的 records。

用法（直接跑這個檔案就能做基本測試）：
  python database.py
"""

import sqlite3
import os

# 資料庫預設檔名，和 main.py 放在同一個資料夾
DEFAULT_DB_FILE = "training.db"


# ---------------------------------------------------------------------------
# 連線輔助
# ---------------------------------------------------------------------------

def _get_connection(db_path: str) -> sqlite3.Connection:
    """
    開啟資料庫連線，並設定兩個常用選項：
    - row_factory：讓查詢結果可以用欄位名稱存取（像 dict），而不是只能用數字索引
    - foreign_keys：開啟外鍵支援（目前沒用到，但養成好習慣）
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 讓 row["date"] 這種寫法可以用
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def init_db(db_path: str = DEFAULT_DB_FILE) -> None:
    """
    建立資料庫和 workouts 資料表。
    如果資料表已經存在，不會重複建立（IF NOT EXISTS 的效果）。
    每次程式啟動都可以安全地呼叫這個函式。
    """
    conn = _get_connection(db_path)
    # cursor 是「游標」，負責執行 SQL 指令
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workouts (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            date     TEXT    NOT NULL,
            exercise TEXT    NOT NULL,
            weight   REAL    NOT NULL,
            sets     INTEGER NOT NULL,
            reps     INTEGER NOT NULL,
            notes    TEXT    DEFAULT ''
        )
    """)

    # commit 才會真正把變更寫進檔案
    conn.commit()
    conn.close()
    print(f"  [DB] initialized: {db_path}")


# ---------------------------------------------------------------------------
# 新增
# ---------------------------------------------------------------------------

def add_workout(
    date: str,
    exercise: str,
    weight: float,
    sets: int,
    reps: int,
    notes: str = "",
    db_path: str = DEFAULT_DB_FILE,
) -> int:
    """
    新增一筆訓練紀錄，回傳新記錄的 id（自動遞增）。

    參數：
      date      - 日期字串，格式 YYYY-MM-DD（例如 "2026-03-12"）
      exercise  - 動作名稱（例如 "Bench Press"）
      weight    - 重量，公斤（例如 60.0）
      sets      - 組數（例如 3）
      reps      - 每組次數（例如 8）
      notes     - 備注，可以留空（例如 "感覺不錯"）
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # ? 是佔位符，sqlite3 會自動處理跳脫，防止 SQL injection
    cursor.execute("""
        INSERT INTO workouts (date, exercise, weight, sets, reps, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (date, exercise, weight, sets, reps, notes))

    conn.commit()
    new_id = cursor.lastrowid  # 取得剛剛插入的那筆記錄的 id
    conn.close()
    return new_id


# ---------------------------------------------------------------------------
# 查詢全部
# ---------------------------------------------------------------------------

def get_all_workouts(db_path: str = DEFAULT_DB_FILE) -> list[dict]:
    """
    回傳所有訓練紀錄，按日期由新到舊排序。
    每筆記錄是一個 dict，key 就是欄位名稱。
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, date, exercise, weight, sets, reps, notes AS note
        FROM workouts
        ORDER BY date DESC, id DESC
    """)

    # sqlite3.Row 可以用 dict() 轉換成普通字典，方便後續處理
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_recent_workouts(limit: int = 10, db_path: str = DEFAULT_DB_FILE) -> list[dict]:
    """
    回傳最近 N 筆訓練紀錄，按日期由新到舊排序。
    limit 預設 10，可以傳入其他數字，例如 get_recent_workouts(5)。
    適合用在「查看最近訓練」的選單。
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # LIMIT ? 讓 SQL 只回傳前 N 筆，不用把全部資料撈出來再切
    cursor.execute("""
        SELECT id, date, exercise, weight, sets, reps, notes AS note
        FROM workouts
        ORDER BY date DESC, id DESC
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_workouts_by_exercise(exercise: str, db_path: str = DEFAULT_DB_FILE) -> list[dict]:
    """
    回傳某個動作的所有歷史紀錄，按日期由舊到新排序。
    搜尋不分大小寫（COLLATE NOCASE），所以 "bench press" 和 "Bench Press" 都能找到。
    適合用在「建議重量」和「趨勢圖」功能。
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # COLLATE NOCASE 讓比對忽略大小寫，不用在 Python 側手動 .lower()
    cursor.execute("""
        SELECT id, date, exercise, weight, sets, reps, notes AS note
        FROM workouts
        WHERE exercise = ? COLLATE NOCASE
        ORDER BY date ASC, id ASC
    """, (exercise,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_total_volume_by_exercise(db_path: str = DEFAULT_DB_FILE) -> list[tuple]:
    """
    計算每個動作的總訓練量（volume），按 volume 由大到小排序。

    volume 公式：weight × reps × sets
    例如：120 kg × 3 reps × 3 sets = 1080

    回傳格式：
      [("Squat", 12000.0), ("Bench Press", 8000.0), ...]
      每個元素是 (動作名稱, 總volume) 的 tuple
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # SUM(weight * reps * sets) 直接在 SQL 裡計算，比在 Python 迴圈裡算更有效率
    # GROUP BY exercise 表示「每個動作分開算」
    # ORDER BY total_volume DESC 表示「volume 最大的排第一」
    cursor.execute("""
        SELECT exercise, SUM(weight * reps * sets) AS total_volume
        FROM workouts
        GROUP BY exercise
        ORDER BY total_volume DESC
    """)

    # 回傳 list of tuple：[("Squat", 12000.0), ...]
    rows = [(row["exercise"], row["total_volume"]) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_pr_by_exercise(db_path: str = DEFAULT_DB_FILE) -> list[tuple]:
    """
    找出每個動作的 PR（Personal Record）= 該動作出現過的最大重量。
    按 PR 重量由大到小排序。

    回傳格式：
      [("Squat", 180.0), ("Bench Press", 120.0), ...]
      每個元素是 (動作名稱, 最大重量) 的 tuple
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # MAX(weight) 取每個動作的最大值
    # GROUP BY exercise 讓每個動作分開計算
    # ORDER BY pr DESC 最重的排第一
    cursor.execute("""
        SELECT exercise, MAX(weight) AS pr
        FROM workouts
        GROUP BY exercise
        ORDER BY pr DESC
    """)

    # 回傳 list of tuple：[("Squat", 180.0), ...]
    rows = [(row["exercise"], row["pr"]) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_training_frequency(db_path: str = DEFAULT_DB_FILE) -> list[tuple]:
    """
    計算每個動作出現的次數（有幾筆紀錄），按次數由多到少排序。

    回傳格式：
      [("Squat", 8), ("Bench Press", 5), ...]
      每個元素是 (動作名稱, 出現次數) 的 tuple
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # COUNT(*) 計算每組有幾筆資料
    # GROUP BY exercise 讓每個動作分開計算
    # ORDER BY frequency DESC 次數最多的排第一
    cursor.execute("""
        SELECT exercise, COUNT(*) AS frequency
        FROM workouts
        GROUP BY exercise
        ORDER BY frequency DESC
    """)

    # 回傳 list of tuple：[("Squat", 8), ...]
    rows = [(row["exercise"], row["frequency"]) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_weekly_training_days(db_path: str = DEFAULT_DB_FILE) -> list[tuple]:
    """
    統計每週訓練了幾天，按週次由新到舊排序。

    回傳格式：
      [("2026-W12", 3), ("2026-W11", 4), ...]
      每個元素是 (週次字串, 訓練天數) 的 tuple
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    # strftime('%Y-%W', date) 把日期轉成 "年-週次"，例如 "2026-12"
    # COUNT(DISTINCT date) 數這週有幾個不同的訓練日（同一天多筆只算一天）
    # GROUP BY week 每週分開統計
    # ORDER BY week DESC 最新的週次排第一
    cursor.execute("""
        SELECT strftime('%Y-W%W', date) AS week,
               COUNT(DISTINCT date)     AS training_days
        FROM workouts
        GROUP BY week
        ORDER BY week DESC
    """)

    # 回傳 list of tuple：[("2026-W12", 3), ...]
    rows = [(row["week"], row["training_days"]) for row in cursor.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# 刪除
# ---------------------------------------------------------------------------

def delete_workout(workout_id: int, db_path: str = DEFAULT_DB_FILE) -> bool:
    """
    根據 id 刪除一筆訓練紀錄。
    回傳 True 表示有刪到；False 表示找不到這個 id。
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))
    conn.commit()

    # rowcount 告訴我們有幾筆資料被影響，0 表示找不到這個 id
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


# ---------------------------------------------------------------------------
# 更新
# ---------------------------------------------------------------------------

def update_workout(
    workout_id: int,
    date: str = None,
    exercise: str = None,
    weight: float = None,
    sets: int = None,
    reps: int = None,
    notes: str = None,
    db_path: str = DEFAULT_DB_FILE,
) -> bool:
    """
    更新一筆訓練紀錄的部分欄位。
    只傳入想修改的欄位，沒傳的欄位保持不變。
    回傳 True 表示更新成功；False 表示找不到這個 id。

    範例：只改重量
      update_workout(3, weight=65.0)
    """
    # 動態組合 SET 子句，只更新有傳值的欄位
    fields = []   # 要更新的欄位名稱，例如 ["weight = ?", "notes = ?"]
    values = []   # 對應的值，例如 [65.0, "新備注"]

    if date     is not None: fields.append("date = ?");     values.append(date)
    if exercise is not None: fields.append("exercise = ?"); values.append(exercise)
    if weight   is not None: fields.append("weight = ?");   values.append(weight)
    if sets     is not None: fields.append("sets = ?");     values.append(sets)
    if reps     is not None: fields.append("reps = ?");     values.append(reps)
    if notes    is not None: fields.append("notes = ?");    values.append(notes)

    # 如果什麼都沒傳，直接回傳 False，不做任何動作
    if not fields:
        return False

    values.append(workout_id)  # WHERE id = ? 的值放最後

    sql = f"UPDATE workouts SET {', '.join(fields)} WHERE id = ?"

    conn = _get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(sql, values)
    conn.commit()

    updated = cursor.rowcount > 0
    conn.close()
    return updated


# ---------------------------------------------------------------------------
# 手動測試（直接 python database.py 執行）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 測試用，用一個獨立的暫存資料庫，跑完後刪除
    TEST_DB = "test_training.db"

    print("=== database.py test start ===\n")

    # 1. init
    init_db(TEST_DB)

    # 2. add records
    id1 = add_workout("2026-03-10", "Bench Press", 60.0, 3, 8, "felt good", TEST_DB)
    id2 = add_workout("2026-03-10", "Squat",       80.0, 3, 5, "",          TEST_DB)
    id3 = add_workout("2026-03-12", "Bench Press", 62.5, 3, 7, "a bit heavy", TEST_DB)
    print(f"  Added 3 records, ids: {id1}, {id2}, {id3}")

    # 3. get all
    print("\n  --- all records ---")
    for row in get_all_workouts(TEST_DB):
        print(f"  [{row['id']}] {row['date']}  {row['exercise']:<15} "
              f"{row['weight']} kg  {row['sets']}x{row['reps']}  {row['notes']}")

    # 4. update
    ok = update_workout(id2, weight=82.5, notes="heavier test", db_path=TEST_DB)
    print(f"\n  update id={id2} weight -> 82.5 kg: {'OK' if ok else 'FAIL'}")

    # 5. delete existing
    ok = delete_workout(id1, TEST_DB)
    print(f"  delete id={id1} (Bench Press 60kg): {'OK' if ok else 'FAIL'}")

    # 6. delete non-existing id
    ok = delete_workout(9999, TEST_DB)
    print(f"  delete id=9999 (not exist): {'OK (expected False)' if not ok else 'FAIL'}")

    # 7. final check
    print("\n  --- remaining records ---")
    for row in get_all_workouts(TEST_DB):
        print(f"  [{row['id']}] {row['date']}  {row['exercise']:<15} "
              f"{row['weight']} kg  {row['sets']}x{row['reps']}  {row['notes']}")

    # cleanup
    os.remove(TEST_DB)
    print(f"\n  [cleanup] removed {TEST_DB}")
    print("\n=== test complete ===")
