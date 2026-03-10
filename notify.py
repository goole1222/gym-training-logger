"""
notify.py — 訓練提醒腳本（獨立執行，不依賴 main.py）

用法：
  python notify.py                    # 使用同資料夾的 training.json
  python notify.py --file my_log.json # 使用指定檔案

功能：
  1. 讀取今天是星期幾
  2. 查看 training.json 的 "schedule" 設定
  3. 如果今天有排課表，對每個動作產生建議重量
  4. 用 Gmail 寄出提醒 Email

前置設定：
  ① 在 notify_config.json 填入你的 Gmail 帳號
  ② 在 training.json 加入 "schedule" 欄位（見下方說明）

schedule 格式範例（放在 training.json 的頂層）：
  "schedule": {
    "monday":   "Max Power Day",
    "thursday": "Max Power Day",
    "saturday": "Max Power Day"
  }
  （沒有列出的星期 = 休息日，腳本直接結束不寄信）
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 因為 notify.py 和 storage.py / suggest.py 在同一個資料夾，可以直接 import
import storage
import suggest

# Python 的 weekday() 回傳 0=Monday … 6=Sunday，這裡轉成英文字串方便對照 schedule
WEEKDAY_NAMES = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

# notify_config.json 與本腳本放在同一個資料夾
# 用 abspath + dirname 是為了讓 Windows 工作排程器執行時也能找到正確路徑
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(_SCRIPT_DIR, "notify_config.json")

# 預設資料檔也用絕對路徑，避免工作排程器切換工作目錄後找不到
DEFAULT_DATA = os.path.join(_SCRIPT_DIR, "training.json")


# ---------------------------------------------------------------------------
# 輔助函式
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """
    讀取 notify_config.json，取得 Gmail 帳號和應用程式密碼。
    如果檔案不存在，印出說明後結束程式。
    """
    if not os.path.exists(CONFIG_FILE):
        print(f"[Error] 找不到設定檔：{CONFIG_FILE}")
        print("請建立 notify_config.json，內容範例：")
        print('  { "email_from": "you@gmail.com",')
        print('    "email_to":   "you@gmail.com",')
        print('    "app_password": "xxxx xxxx xxxx xxxx" }')
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_email_body(
    template_name: str,
    enriched: list[dict],
    today_str: str,
    weekday_name: str,
) -> str:
    """
    組合 Email 正文。

    enriched 清單裡每個元素是：
      { exercise, sets, reps, suggestion, reason }
    """
    day_display = weekday_name.capitalize()   # "Monday", "Thursday" …

    lines = [
        f"Today is {day_display}, {today_str}.",
        f"Scheduled workout: {template_name}",
        "",
        "Exercise Plan & Suggested Weights",
        "─" * 52,
    ]

    for item in enriched:
        # 格式：動作名稱（左對齊）  組數×次數  →  建議重量
        lines.append(
            f"  {item['exercise']:<22}  "
            f"{item['sets']} sets × {item['reps']} reps"
            f"   →  {item['suggestion']}"
        )
        # 在下一行縮排顯示原因
        lines.append(f"      {item['reason']}")
        lines.append("")

    lines += [
        "─" * 52,
        "Good luck today! 💪",
        "",
        "— Gym Training Logger (auto notify)",
    ]

    return "\n".join(lines)


def _send_email(config: dict, subject: str, body: str) -> None:
    """
    用 Gmail SMTP（SSL port 465）寄信。

    config 需要包含：
      email_from   - 寄件人 Gmail 地址
      email_to     - 收件人地址（可以跟寄件人一樣）
      app_password - Gmail 應用程式密碼（16碼，帶空格也沒關係）
    """
    # 建立郵件物件
    msg = MIMEMultipart()
    msg["From"]    = config["email_from"]
    msg["To"]      = config["email_to"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))   # 純文字格式

    # 連接 Gmail SMTP 伺服器（SSL 加密，port 465）
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(config["email_from"], config["app_password"])
        server.send_message(msg)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    # ── 步驟 0：解析命令列參數 ──────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Gym Training Notifier — 根據排程寄出訓練提醒 Email"
    )
    parser.add_argument(
        "--file",
        default=DEFAULT_DATA,
        help=f"訓練資料 JSON 路徑（預設：{DEFAULT_DATA}）",
    )
    args = parser.parse_args()

    # ── 步驟 1：讀取資料和排程設定 ──────────────────────────────
    data     = storage.load_data(args.file)
    schedule = data.get("schedule", {})   # 如果 JSON 沒有 schedule 欄位就用空 dict

    # ── 步驟 2：判斷今天有沒有訓練 ──────────────────────────────
    today        = date.today()
    today_str    = today.isoformat()                  # "2026-03-09"
    weekday_name = WEEKDAY_NAMES[today.weekday()]     # "sunday", "monday" …

    template_name = schedule.get(weekday_name)        # 今天對應的模板名稱
    if not template_name:
        # 今天是休息日，靜默結束（不印錯誤，方便排程器每天都跑）
        print(f"No training scheduled for {weekday_name.capitalize()}. Skipping.")
        sys.exit(0)

    # ── 步驟 3：找到對應的模板 ──────────────────────────────────
    templates = data.get("templates", [])
    template  = next(
        (t for t in templates if t["name"].lower() == template_name.lower()),
        None,
    )
    if template is None:
        print(f"[Warning] Template '{template_name}' not found in {args.file}.")
        sys.exit(1)

    # ── 步驟 4：產生建議重量 ─────────────────────────────────────
    # suggest.generate_suggestions() 回傳每個動作的建議字典清單
    # 鍵：exercise, suggestion, reason, avg_weight_recent
    suggestions_raw = suggest.generate_suggestions(data["records"])

    # 建立 {動作名稱小寫: 建議字典} 的查詢表
    sugg_map = {s["exercise"].lower(): s for s in suggestions_raw}

    # 逐一對模板裡的動作配對建議
    enriched = []
    for item in template["items"]:
        ex_key = item["exercise"].lower()
        sugg   = sugg_map.get(ex_key)

        if sugg:
            # 有歷史紀錄，使用 suggest 模組算出的建議
            entry = {
                "exercise":   item["exercise"],
                "sets":       item["sets"],
                "reps":       item["reps"],
                "suggestion": sugg["suggestion"],
                "reason":     sugg["reason"],
            }
        else:
            # 還沒有歷史紀錄（第一次練這個動作）
            entry = {
                "exercise":   item["exercise"],
                "sets":       item["sets"],
                "reps":       item["reps"],
                "suggestion": "Start light — no history yet",
                "reason":     "No previous records found for this exercise.",
            }
        enriched.append(entry)

    # ── 步驟 5：組合並寄出 Email ─────────────────────────────────
    config  = _load_config()
    subject = f"[Gym] Today: {template_name} ({today_str})"
    body    = _build_email_body(template_name, enriched, today_str, weekday_name)

    print(f"Sending to {config['email_to']} ...")
    try:
        _send_email(config, subject, body)
        print("✔ Email sent!")
    except Exception as e:
        print(f"[Error] Failed to send email: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
