"""Techmeme RSS 收集器。GitHub Actions 每 6 小時執行一次。

抓 feed.xml，把新項目合併進 data/YYYY-MM-DD.json。
每個 JSON 檔是 {permalink_id: item} 的 dict，重複執行只會新增不會重複。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

from feed_utils import parse_feed

FEED_URL = "https://www.techmeme.com/feed.xml"
DATA_DIR = Path(__file__).parent / "data"

# RSS 端點是給訂閱器用的，UA 表明自己是 feed reader
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TechmemeLite/1.0; feed reader)",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


def fetch_feed(max_retries: int = 4) -> str:
    """抓 feed.xml，失敗時換一組瀏覽器 UA 再試。"""
    fallback_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    }
    last_err: Exception | None = None
    for attempt in range(max_retries):
        headers = HEADERS if attempt % 2 == 0 else fallback_headers
        try:
            resp = requests.get(FEED_URL, headers=headers, timeout=30)
            resp.raise_for_status()
            if "<rss" not in resp.text[:500] and "<feed" not in resp.text[:500]:
                raise ValueError("回應內容不是 RSS")
            return resp.text
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"抓取 {FEED_URL} 失敗：{last_err}")


def merge_items(items: list[dict], data_dir: Path = DATA_DIR) -> int:
    """把項目按日期合併進 data/*.json，回傳新增的筆數。"""
    data_dir.mkdir(exist_ok=True)
    by_date: dict[str, list[dict]] = {}
    for it in items:
        by_date.setdefault(it["date"], []).append(it)

    added = 0
    for day, day_items in sorted(by_date.items()):
        path = data_dir / f"{day}.json"
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # 檔案壞掉就重建，寧可重抓也不要整個流程卡死
                existing = {}
        before = len(existing)
        for it in day_items:
            existing.setdefault(it["permalink_id"], it)
        if len(existing) > before:
            added += len(existing) - before
            path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8",
            )
    return added


def main() -> int:
    xml = fetch_feed()
    items = parse_feed(xml)
    if not items:
        print("feed 解析出 0 則項目，Techmeme feed 格式可能改了", file=sys.stderr)
        return 1
    added = merge_items(items)
    print(f"feed 內共 {len(items)} 則，新增 {added} 則")
    return 0


if __name__ == "__main__":
    sys.exit(main())
