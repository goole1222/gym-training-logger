"""
dashboard.py — Gym Training Logger Web Dashboard

使用 Streamlit 顯示訓練資料，資料來自 database.py。

執行方式：
  streamlit run dashboard.py
"""

import streamlit as st
import database


# ---------------------------------------------------------------------------
# 頁面基本設定
# ---------------------------------------------------------------------------

# set_page_config 必須是第一個 Streamlit 指令，設定瀏覽器頁籤標題和版面寬度
st.set_page_config(
    page_title="Gym Training Dashboard",
    layout="wide",   # "wide" 讓內容佔滿整個視窗寬度
)

# 顯示頁面大標題
st.title("Gym Training Dashboard")


# ---------------------------------------------------------------------------
# 區塊 1：Volume by Exercise
# ---------------------------------------------------------------------------

st.header("Volume by Exercise")
st.caption("Total volume = weight × sets × reps，數字越大代表這個動作練的總量越多")

# 從資料庫取得每個動作的總訓練量，回傳格式：[(exercise, total_volume), ...]
volume_rows = database.get_total_volume_by_exercise()

if not volume_rows:
    # 如果沒有資料，顯示提示訊息
    st.info("No records yet. Add some workouts first!")
else:
    # 把 list of tuple 轉成 list of dict，這樣 st.table 會自動用 key 當欄位標題
    # 把資料轉成 {動作名稱: 總量} 的 dict
    # st.bar_chart 接受這種格式：key 是 x 軸標籤，value 是 bar 的高度
    volume_dict = {exercise: round(total_vol, 1) for exercise, total_vol in volume_rows}

    # 直接畫 bar chart，Streamlit 會自動處理 x/y 軸
    st.bar_chart(volume_dict)


# ---------------------------------------------------------------------------
# 區塊 2：PR Records
# ---------------------------------------------------------------------------

# st.divider 畫一條水平分隔線，讓版面比較清楚
st.divider()

st.header("Personal Records (PR)")
st.caption("每個動作出現過的最大重量")

# 從資料庫取得每個動作的 PR，回傳格式：[(exercise, pr_weight), ...]
pr_rows = database.get_pr_by_exercise()

if not pr_rows:
    st.info("No records yet.")
else:
    pr_data = [
        {"Exercise": exercise, "PR (kg)": pr}
        for exercise, pr in pr_rows
    ]
    st.dataframe(pr_data, hide_index=True)


# ---------------------------------------------------------------------------
# 區塊 3：Training Streak
# ---------------------------------------------------------------------------

st.divider()

st.header("Training Streak")
st.caption("連續訓練天數統計")

# 從資料庫計算 streak，回傳格式：{"current_streak": N, "longest_streak": N}
streak = database.get_training_streak()

# st.columns 把這一行切成兩欄，讓兩個數字並排顯示
col1, col2 = st.columns(2)

# st.metric 專門用來顯示「一個大數字 + 標題」的卡片樣式
with col1:
    st.metric(label="Current Streak", value=f"{streak['current_streak']} days")

with col2:
    st.metric(label="Longest Streak", value=f"{streak['longest_streak']} days")


# ---------------------------------------------------------------------------
# 區塊 4：Weekly Training Days
# ---------------------------------------------------------------------------

st.divider()

st.header("Weekly Training Days")
st.caption("每週實際去訓練幾天，最多 7 天")

# 從資料庫取得每週訓練天數，回傳格式：[("2026-W12", 3), ("2026-W11", 4), ...]
# 資料庫回傳的順序是最新週在前，所以要 reverse 讓圖表從左到右是時間軸
weekly_rows = database.get_weekly_training_days()

if not weekly_rows:
    st.info("No records yet.")
else:
    # reversed() 把順序反過來：最舊的週次排左邊，最新的排右邊
    # 這樣 bar chart 看起來像時間軸（左舊右新）
    weekly_dict = {week: days for week, days in reversed(weekly_rows)}

    # 畫 bar chart，x 軸是週次，y 軸是訓練天數
    st.bar_chart(weekly_dict)
