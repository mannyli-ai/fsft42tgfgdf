"""Techmeme Lite：讀取 GitHub Actions 收集的 Techmeme 新聞標題，
翻譯成台灣繁體中文，輸出 xlsx（連結可直接點）。

資料來源是 repo 內 data/ 目錄的每日 JSON（由 .github/workflows/collect.yml
每 6 小時自動收集）。app 本身不連 techmeme.com。
流程分兩段：先載入預覽（免費），確認後再翻譯（花 OpenAI 額度）。
"""

from datetime import timedelta

import pandas as pd
import streamlit as st

from data_store import list_available_dates, load_range
from exporter import build_xlsx
from translator import translate_items, BATCH_SIZE

st.set_page_config(page_title="Techmeme Lite", page_icon="📰", layout="wide")

MAX_RANGE_DAYS = 31


# ---------- 密碼閘門 ----------
def _get_secret(name: str) -> str:
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""  # 本機沒有 secrets.toml 時屬正常情況


def check_password() -> bool:
    """Secrets 有設 APP_PASSWORD 時啟用密碼閘門，沒設就直接放行（本機開發用）。"""
    import hmac

    app_password = _get_secret("APP_PASSWORD")
    if not app_password:
        return True
    if st.session_state.get("password_ok"):
        return True

    def on_enter():
        # compare_digest 防時序攻擊；驗證後立刻清掉輸入框裡的密碼
        if hmac.compare_digest(st.session_state.get("pwd_input", ""), app_password):
            st.session_state["password_ok"] = True
        else:
            st.session_state["password_ok"] = False
        st.session_state["pwd_input"] = ""

    st.title("📰 Techmeme Lite")
    st.text_input("請輸入密碼", type="password", key="pwd_input", on_change=on_enter)
    if st.session_state.get("password_ok") is False:
        st.error("密碼錯誤")
    return False


if not check_password():
    st.stop()

# ---------- Session state ----------
if "raw_items" not in st.session_state:
    st.session_state.raw_items = None
if "translated_items" not in st.session_state:
    st.session_state.translated_items = None

available = list_available_dates()

# ---------- Sidebar ----------
with st.sidebar:
    st.title("📰 Techmeme Lite")
    st.caption("GitHub Actions 每 6 小時自動收集 Techmeme 新聞，這裡翻譯標題成台灣繁體中文並輸出 Excel。")

    if available:
        st.info(f"目前收集到 **{available[0]} ~ {available[-1]}**，共 {len(available)} 天。")
        default_range = (max(available[0], available[-1] - timedelta(days=1)), available[-1])
        date_range = st.date_input(
            "日期區間",
            value=default_range,
            min_value=available[0],
            max_value=available[-1],
            help="資料從 collector 開始運作那天起累積。"
            "Techmeme 以美東時間換日，最新一天的內容會隨每次收集逐步補齊。",
        )
    else:
        date_range = None

    st.divider()
    # 優先讀 Streamlit secrets（部署後設定一次就不用每次輸入），
    # 沒設定 secrets 時退回手動輸入框
    saved_key = ""
    try:
        saved_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass  # 本機沒有 secrets.toml 時 st.secrets 會丟例外，屬正常情況

    if saved_key:
        api_key = saved_key
        st.success("已從 secrets 讀取 OpenAI API Key")
    else:
        api_key = st.text_input(
            "OpenAI API Key",
            type="password",
            help="只在翻譯階段需要。金鑰只存在這個瀏覽器工作階段，不會寫入任何檔案。"
            "想免輸入請在 Streamlit Cloud 的 app 設定 → Secrets 加入 OPENAI_API_KEY。",
        )
    model = st.selectbox(
        "翻譯模型",
        ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"],
        index=0,
        help="gpt-4o-mini 已經夠用而且最便宜。",
    )

# ---------- 還沒有任何資料 ----------
if not available:
    st.header("還沒有資料")
    st.write(
        "data/ 目錄是空的，代表 collector 還沒跑過。到 GitHub repo 的 "
        "**Actions** 分頁，選左側的 **Collect Techmeme RSS**，按 **Run workflow** "
        "手動跑第一次（之後每 6 小時會自動跑）。跑完約一分鐘後重新整理這個頁面。"
    )
    st.write("本機開發的話，直接執行 `python collector.py` 即可。")
    st.stop()

# date_input 在使用者只點了起始日、還沒點結束日時會回傳單一元素，
# 極端情況下（widget 尚未初始化）會是 None，都要擋
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
elif isinstance(date_range, tuple) and len(date_range) == 1:
    start_date = end_date = date_range[0]
elif date_range is not None and not isinstance(date_range, tuple):
    start_date = end_date = date_range
else:
    st.info("請在左側選好完整的日期區間（起始日和結束日都要點）。")
    st.stop()

range_days = (end_date - start_date).days + 1

# ---------- 第一段：載入 ----------
st.header("步驟一：載入新聞")
st.write(
    f"目前選擇 **{start_date} ~ {end_date}**（{range_days} 天）。"
    f"載入的是已收集好的資料，這一步免費，不需要 API key。"
)

if range_days > MAX_RANGE_DAYS:
    st.error(f"區間請勿超過 {MAX_RANGE_DAYS} 天（目前 {range_days} 天），太長的區間翻譯又慢又貴。")
    st.stop()

if st.button("📥 載入", type="primary"):
    items, missing = load_range(start_date, end_date)
    st.session_state.raw_items = items
    st.session_state.translated_items = None  # 新載入的資料，舊翻譯作廢
    if missing:
        missing_str = "、".join(d.isoformat() for d in missing)
        st.warning(f"以下日期沒有資料（collector 當時尚未運作）：{missing_str}")

raw = st.session_state.raw_items
if raw is not None:
    if len(raw) == 0:
        st.warning("這個區間沒有任何新聞資料。")
    else:
        st.success(f"載入 {len(raw)} 則新聞。先確認內容沒問題，再進行翻譯。")
        preview_df = pd.DataFrame(raw)[["date", "title", "article_url"]].rename(
            columns={"date": "日期", "title": "原始標題", "article_url": "原文連結"}
        )
        st.dataframe(
            preview_df,
            height=300,
            column_config={"原文連結": st.column_config.LinkColumn("原文連結")},
        )

# ---------- 第二段：翻譯 ----------
if raw:
    st.header("步驟二：翻譯")
    n_calls = -(-len(raw) // BATCH_SIZE)  # ceiling division
    st.write(f"共 {len(raw)} 則標題，會分成約 {n_calls} 次 API 呼叫（每次 {BATCH_SIZE} 則）。")

    if st.button("🌐 開始翻譯", type="primary", disabled=not api_key):
        if not api_key:
            st.error("請先在左側輸入 OpenAI API Key。")
        else:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            progress = st.progress(0.0, text="翻譯中……")

            def on_batch(i, total):
                progress.progress(min(i / total, 1.0), text=f"翻譯批次 {min(i + 1, total)}/{total}")

            try:
                st.session_state.translated_items = translate_items(
                    raw, client, model=model, on_progress=on_batch
                )
                progress.progress(1.0, text="翻譯完成")
            except Exception as e:
                st.error(f"翻譯失敗：{e}")

    if not api_key:
        st.info("翻譯前請先在左側輸入 OpenAI API Key。")

# ---------- 結果與下載 ----------
translated = st.session_state.translated_items
if translated:
    st.header("結果")
    display_cols = {
        "date": "日期",
        "title": "原始標題",
        "title_zh": "翻譯標題",
        "article_url": "原文連結",
        "techmeme_url": "Techmeme 連結",
    }
    df = pd.DataFrame(translated)[list(display_cols.keys())].rename(columns=display_cols)

    st.dataframe(
        df,
        height=500,
        column_config={
            "原文連結": st.column_config.LinkColumn("原文連結"),
            "Techmeme 連結": st.column_config.LinkColumn("Techmeme 連結"),
        },
    )

    st.download_button(
        "📥 下載 Excel",
        data=build_xlsx(translated),
        file_name=f"techmeme_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
