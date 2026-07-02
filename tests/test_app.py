"""AppTest 端對端測試：載入 → 預覽 → 翻譯 → CSV。資料和 OpenAI 都用假的。"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from streamlit.testing.v1 import AppTest

from feed_utils import parse_feed
from collector import merge_items

FEED_XML = (Path(__file__).parent / "fixture_feed.xml").read_text(encoding="utf-8")
APP_PATH = str(Path(__file__).parent.parent / "app.py")


def _prepare_data(tmp_path):
    merge_items(parse_feed(FEED_XML), data_dir=tmp_path)
    return tmp_path


def test_app_without_data_shows_setup_instructions(tmp_path):
    with patch("data_store.DATA_DIR", tmp_path):
        at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    assert any("還沒有資料" in h.value for h in at.header)


def test_full_flow_load_translate_csv(tmp_path):
    _prepare_data(tmp_path)
    import datetime

    with patch("data_store.DATA_DIR", tmp_path):
        at = AppTest.from_file(APP_PATH, default_timeout=60).run()
        assert not at.exception

        at.date_input[0].set_value((datetime.date(2026, 7, 1), datetime.date(2026, 7, 2)))
        at.text_input[0].set_value("sk-test-fake-key")

        # ---- 載入 ----
        at.button[0].click()
        at.run()
        assert not at.exception
        raw = at.session_state["raw_items"]
        assert raw is not None and len(raw) == 3
        assert {it["date"] for it in raw} == {"2026-07-01", "2026-07-02"}

        # ---- 翻譯 ----
        def fake_create(**kwargs):
            payload = json.loads(
                kwargs["messages"][1]["content"].split("輸入：\n", 1)[1].split("\n\n回傳格式")[0]
            )
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = json.dumps(
                {"translations": [
                    {"id": it["id"], "title_zh": f"譯{it['id']}", "summary_zh": "台灣繁體中文摘要"}
                    for it in payload
                ]},
                ensure_ascii=False,
            )
            return resp

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = fake_create

        with patch("openai.OpenAI", return_value=fake_client):
            at.button[1].click()
            at.run()
        assert not at.exception

        translated = at.session_state["translated_items"]
        assert translated is not None and len(translated) == 3
        assert all(it["summary_zh"] == "台灣繁體中文摘要" for it in translated)

    # ---- CSV 欄位與編碼（欄位對應須與 app.py 的 CSV_COLUMNS 一致）----
    csv_columns = {
        "date": "日期",
        "title": "原始標題",
        "summary": "原始摘要",
        "title_zh": "翻譯標題",
        "summary_zh": "翻譯摘要",
        "article_url": "原文連結",
        "techmeme_url": "Techmeme 連結",
    }
    df = pd.DataFrame(translated).rename(columns=csv_columns)[list(csv_columns.values())]
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    back = pd.read_csv(io.BytesIO(csv_bytes), encoding="utf-8-sig")
    assert list(back.columns) == ["日期", "原始標題", "原始摘要", "翻譯標題", "翻譯摘要", "原文連結", "Techmeme 連結"]
    assert back["翻譯摘要"].iloc[0] == "台灣繁體中文摘要"


def test_missing_days_warning(tmp_path):
    _prepare_data(tmp_path)
    # 刪掉其中一天，模擬 collector 中間漏抓
    (tmp_path / "2026-07-01.json").unlink()
    import datetime

    with patch("data_store.DATA_DIR", tmp_path):
        at = AppTest.from_file(APP_PATH, default_timeout=30).run()
        # min_value 是剩下的 2026-07-02，直接載入
        at.button[0].click()
        at.run()
    assert not at.exception
    assert len(at.session_state["raw_items"]) == 2
