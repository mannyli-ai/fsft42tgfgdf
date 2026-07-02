"""feed 解析、collector 合併、資料讀取、翻譯的單元測試。跑法：pytest。"""

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from feed_utils import parse_feed, clean_url
from collector import merge_items, fetch_feed
from data_store import list_available_dates, load_range
from translator import translate_items, _parse_response

FEED_XML = (Path(__file__).parent / "fixture_feed.xml").read_text(encoding="utf-8")


# ---------- feed 解析 ----------

def test_parse_feed_extracts_items():
    items = parse_feed(FEED_XML)
    titles = [it["title"] for it in items]
    assert any("CSOP SK Hynix" in t for t in titles)
    assert any("banning social media" in t for t in titles)
    assert any("CarbonSix" in t for t in titles)
    # 5 個 item：3 有效 + 1 重複 guid + 1 沒有外站連結
    assert len(items) == 3


def test_parse_feed_dedupes_by_guid():
    items = parse_feed(FEED_XML)
    ids = [it["permalink_id"] for it in items]
    assert len(ids) == len(set(ids))
    etf = next(it for it in items if it["permalink_id"] == "a260702p9")
    assert "CSOP" in etf["title"]  # 保留第一次出現的，不是 duplicate 那則


def test_parse_feed_skips_items_without_external_link():
    items = parse_feed(FEED_XML)
    assert not any("without external link" in it["title"] for it in items)
    assert all(not it["article_url"].startswith("https://www.techmeme.com") for it in items)


def test_parse_feed_date_from_guid():
    items = parse_feed(FEED_XML)
    etf = next(it for it in items if "CSOP" in it["title"])
    assert etf["date"] == "2026-07-02"
    carbon = next(it for it in items if "CarbonSix" in it["title"])
    assert carbon["date"] == "2026-07-01"


def test_parse_feed_excerpt_and_empty_excerpt():
    items = parse_feed(FEED_XML)
    etf = next(it for it in items if "CSOP" in it["title"])
    assert "Hong Kong fund tied to SK Hynix" in etf["summary"]
    pew = next(it for it in items if "banning social media" in it["title"])
    assert pew["summary"] == ""


def test_parse_feed_strips_tracking_params():
    items = parse_feed(FEED_XML)
    etf = next(it for it in items if "CSOP" in it["title"])
    assert "utm_source" not in etf["article_url"]
    assert "accessToken=abc123" in etf["article_url"]  # 非追蹤參數要保留


def test_parse_feed_techmeme_url_https_no_fragment():
    items = parse_feed(FEED_XML)
    for it in items:
        assert it["techmeme_url"].startswith("https://www.techmeme.com/")
        assert "#" not in it["techmeme_url"]


def test_clean_url_edge_cases():
    assert clean_url("") == ""
    assert clean_url("https://a.com/x?utm_campaign=1&id=2#frag") == "https://a.com/x?id=2"


def test_parse_feed_garbage_input():
    assert parse_feed("not xml at all") == []
    assert parse_feed("<rss><channel></channel></rss>") == []


# ---------- collector 合併 ----------

def test_merge_items_creates_daily_files(tmp_path):
    items = parse_feed(FEED_XML)
    added = merge_items(items, data_dir=tmp_path)
    assert added == 3
    assert (tmp_path / "2026-07-02.json").exists()
    assert (tmp_path / "2026-07-01.json").exists()
    day2 = json.loads((tmp_path / "2026-07-02.json").read_text(encoding="utf-8"))
    assert set(day2.keys()) == {"a260702p9", "a260702p8"}


def test_merge_items_idempotent(tmp_path):
    items = parse_feed(FEED_XML)
    assert merge_items(items, data_dir=tmp_path) == 3
    assert merge_items(items, data_dir=tmp_path) == 0  # 再跑一次不會重複


def test_merge_items_appends_new_only(tmp_path):
    items = parse_feed(FEED_XML)
    merge_items(items[:1], data_dir=tmp_path)
    added = merge_items(items, data_dir=tmp_path)
    assert added == 2


def test_merge_items_recovers_from_corrupt_file(tmp_path):
    (tmp_path / "2026-07-02.json").write_text("{corrupt", encoding="utf-8")
    items = [it for it in parse_feed(FEED_XML) if it["date"] == "2026-07-02"]
    added = merge_items(items, data_dir=tmp_path)
    assert added == 2
    data = json.loads((tmp_path / "2026-07-02.json").read_text(encoding="utf-8"))
    assert len(data) == 2


def test_fetch_feed_retries_then_raises(monkeypatch):
    import collector as collector_mod

    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        raise ConnectionError("boom")

    monkeypatch.setattr(collector_mod.requests, "get", fake_get)
    monkeypatch.setattr(collector_mod.time, "sleep", lambda s: None)
    try:
        fetch_feed(max_retries=3)
        raised = False
    except RuntimeError as e:
        raised = True
        assert "boom" in str(e)
    assert raised and calls["n"] == 3


def test_fetch_feed_rejects_non_rss(monkeypatch):
    import collector as collector_mod

    resp = MagicMock()
    resp.text = "<html>blocked</html>"
    resp.raise_for_status = MagicMock()
    monkeypatch.setattr(collector_mod.requests, "get", lambda *a, **k: resp)
    monkeypatch.setattr(collector_mod.time, "sleep", lambda s: None)
    try:
        fetch_feed(max_retries=2)
        raised = False
    except RuntimeError:
        raised = True
    assert raised


# ---------- data_store ----------

def _write_store(tmp_path):
    merge_items(parse_feed(FEED_XML), data_dir=tmp_path)


def test_list_available_dates(tmp_path):
    assert list_available_dates(tmp_path) == []
    _write_store(tmp_path)
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")  # 非日期檔要忽略
    assert list_available_dates(tmp_path) == [date(2026, 7, 1), date(2026, 7, 2)]


def test_load_range_and_missing_days(tmp_path):
    _write_store(tmp_path)
    items, missing = load_range(date(2026, 6, 30), date(2026, 7, 2), data_dir=tmp_path)
    assert len(items) == 3
    assert missing == [date(2026, 6, 30)]
    # 同一天內照 permalink 流水號排序
    day2 = [it for it in items if it["date"] == "2026-07-02"]
    assert [it["permalink_id"] for it in day2] == ["a260702p8", "a260702p9"]


def test_load_range_single_day(tmp_path):
    _write_store(tmp_path)
    items, missing = load_range(date(2026, 7, 1), date(2026, 7, 1), data_dir=tmp_path)
    assert len(items) == 1 and not missing
    assert "CarbonSix" in items[0]["title"]


# ---------- 翻譯（沿用之前的測試）----------

def _make_fake_client(responder):
    client = MagicMock()

    def create(**kwargs):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = responder(kwargs["messages"])
        return resp

    client.chat.completions.create.side_effect = create
    return client


def _sample_items(n):
    return [
        {
            "date": "2026-07-02",
            "title": f"English title {i}",
            "summary": f"English summary {i}" if i % 2 == 0 else "",
            "article_url": f"https://example.com/{i}",
            "techmeme_url": f"https://www.techmeme.com/260702/p{i}",
            "permalink_id": f"a260702p{i}",
        }
        for i in range(n)
    ]


def test_translate_happy_path():
    def responder(messages):
        payload = json.loads(messages[1]["content"].split("輸入：\n", 1)[1].split("\n\n回傳格式")[0])
        return json.dumps(
            {"translations": [
                {"id": it["id"], "title_zh": f"中文標題{it['id']}", "summary_zh": f"中文摘要{it['id']}" if it["summary"] else ""}
                for it in payload
            ]},
            ensure_ascii=False,
        )

    items = _sample_items(23)
    client = _make_fake_client(responder)
    out = translate_items(items, client, batch_size=10)
    assert len(out) == 23
    assert client.chat.completions.create.call_count == 3
    assert out[0]["title_zh"] == "中文標題0"
    assert out[1]["summary_zh"] == ""
    assert out[5]["article_url"] == "https://example.com/5"


def test_translate_handles_markdown_fenced_json():
    def responder(messages):
        return '```json\n{"translations": [{"id": 0, "title_zh": "標題", "summary_zh": "摘要"}]}\n```'

    out = translate_items(_sample_items(1), _make_fake_client(responder))
    assert out[0]["title_zh"] == "標題"


def test_translate_marks_failures_without_crashing():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("rate limit")
    out = translate_items(_sample_items(2), client)
    assert len(out) == 2
    assert "翻譯失敗" in out[0]["title_zh"]
    assert client.chat.completions.create.call_count == 2


def test_parse_response_rejects_out_of_range_ids():
    parsed = _parse_response('{"translations": [{"id": 99, "title_zh": "x"}, {"id": 0, "title_zh": "ok"}]}', 2)
    assert 99 not in parsed
    assert parsed[0]["title_zh"] == "ok"
