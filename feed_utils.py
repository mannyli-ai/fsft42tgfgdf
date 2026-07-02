"""Techmeme RSS feed 解析。

feed.xml 每則 item 的結構：
- <title>：Techmeme 的編輯標題，結尾帶「(來源)」
- <link> / <guid>：Techmeme permalink，格式 /YYMMDD/pN#aYYMMDDpN，
  其中 YYMMDD 就是發布日期（美東時間）
- <description>：HTML，包含指向外站原文的連結，
  標題粗體之後接 &mdash; 和原文開頭節錄
"""

from __future__ import annotations

import re

import feedparser
from bs4 import BeautifulSoup

GUID_RE = re.compile(r"/(\d{6})/p(\d+)")

# 想剔除的追蹤參數
EXCLUDE_QS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_", "mibextid",
}


def clean_url(url: str) -> str:
    """移除常見追蹤參數與 fragment。"""
    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

    try:
        if not url:
            return url
        p = urlparse(url)
        q = [
            (k, v)
            for (k, v) in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in EXCLUDE_QS and not k.lower().startswith("utm_")
        ]
        return urlunparse(p._replace(query=urlencode(q, doseq=True), fragment=""))
    except Exception:
        return url


def _guid_to_date(yymmdd: str) -> str:
    """permalink 的 YYMMDD 轉 YYYY-MM-DD。Techmeme 創立於 2005 年，一律 20xx。"""
    return f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"


def _extract_article_url(description_html: str) -> str:
    """從 description HTML 取第一個外站連結（跳過 techmeme.com 自己的）。"""
    soup = BeautifulSoup(description_html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if "techmeme.com" in href.lower():
            continue
        return clean_url(href)
    return ""


def _extract_excerpt(description_html: str) -> str:
    """取粗體標題之後、以 em-dash 分隔的原文節錄。"""
    soup = BeautifulSoup(description_html or "", "html.parser")
    bold = soup.find("b") or soup.find("strong")
    full_text = soup.get_text(" ", strip=True)
    if bold is not None:
        headline = bold.get_text(" ", strip=True)
        idx = full_text.find(headline)
        tail = full_text[idx + len(headline):] if idx >= 0 else full_text
    else:
        tail = full_text
    for dash in ("\u2014", "\u2013"):
        pos = tail.find(dash)
        if pos >= 0:
            excerpt = re.sub(r"\s+", " ", tail[pos + 1:]).strip(" -\u2014\u2013")
            return excerpt
    return ""


def parse_feed(xml_text: str) -> list[dict]:
    """把 feed.xml 內容解析成新聞項目清單。

    回傳的每個 dict 欄位：date, title, summary, article_url,
    techmeme_url, permalink_id。無法解析出 permalink 的項目略過。
    """
    parsed = feedparser.parse(xml_text)
    items: list[dict] = []
    seen: set[str] = set()

    for entry in parsed.entries:
        techmeme_url = (entry.get("link") or entry.get("id") or "").strip()
        m = GUID_RE.search(techmeme_url)
        if not m:
            continue
        permalink_id = f"a{m.group(1)}p{m.group(2)}"
        if permalink_id in seen:
            continue
        seen.add(permalink_id)

        title = re.sub(r"\s+", " ", (entry.get("title") or "").strip())
        description = ""
        if entry.get("summary"):
            description = entry["summary"]
        elif entry.get("description"):
            description = entry["description"]

        article_url = _extract_article_url(description)
        if not title or not article_url:
            continue

        items.append(
            {
                "date": _guid_to_date(m.group(1)),
                "title": title,
                "summary": _extract_excerpt(description),
                "article_url": article_url,
                "techmeme_url": techmeme_url.split("#")[0].replace("http://", "https://"),
                "permalink_id": permalink_id,
            }
        )

    return items
