"""讀取 collector 存下來的 data/*.json。app 只從這裡拿資料，不碰網路。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def list_available_dates(data_dir: Path | None = None) -> list[date]:
    """回傳目前有資料的日期（遞增排序）。"""
    data_dir = data_dir if data_dir is not None else DATA_DIR
    if not data_dir.exists():
        return []
    dates = []
    for p in data_dir.glob("*.json"):
        try:
            dates.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return sorted(dates)


def load_range(
    start: date, end: date, data_dir: Path | None = None
) -> tuple[list[dict], list[date]]:
    """載入日期區間內的新聞。

    回傳 (items, missing_days)。missing_days 是區間內沒有資料檔的日期，
    讓 UI 告訴使用者哪幾天還沒收集到。
    """
    data_dir = data_dir if data_dir is not None else DATA_DIR
    items: list[dict] = []
    missing: list[date] = []
    day = start
    while day <= end:
        path = data_dir / f"{day.isoformat()}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # permalink 的流水號代表當天的發布順序，照它排
                items.extend(
                    sorted(data.values(), key=lambda it: _perma_sort_key(it))
                )
            except json.JSONDecodeError:
                missing.append(day)
        else:
            missing.append(day)
        day += timedelta(days=1)
    return items, missing


def _perma_sort_key(item: dict) -> tuple:
    pid = item.get("permalink_id", "")
    # aYYMMDDpN → (YYMMDD, N)
    try:
        d, n = pid[1:].split("p")
        return (d, int(n))
    except (ValueError, IndexError):
        return ("", 0)
