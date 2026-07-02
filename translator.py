"""用 OpenAI API 把 Techmeme 標題翻譯成台灣繁體中文。

一次 API 呼叫批次翻譯多則標題，要求模型回傳 JSON，逐則對應回原始項目。
"""

from __future__ import annotations

import json

BATCH_SIZE = 20  # 只翻標題，一批可以塞更多

SYSTEM_PROMPT = """你是專業的科技新聞編譯，把英文科技新聞標題翻譯成台灣使用的繁體中文。

規則：
1. 使用台灣的科技產業慣用詞彙（例如晶片不是芯片、軟體不是軟件、資料不是數據、雲端不是雲、網路不是網絡、人工智慧或 AI 不是人工智能）。
2. 公司名、產品名、人名保留英文原文（例如 OpenAI、iPhone、Sam Altman）。
3. 金額與數字照原文保留（例如 $40M 可譯為 4,000 萬美元）。
4. 翻譯要自然通順，像台灣科技媒體的標題寫法，不要逐字直譯。
5. 標題結尾若有「(來源名)」的括號註記，翻譯時保留原文不翻。
6. 只回傳 JSON，不要加任何說明文字或 markdown 標記。"""

USER_PROMPT_TEMPLATE = """請翻譯以下 {count} 則新聞標題。

輸入：
{payload}

回傳格式（JSON object，translations 陣列的每個元素對應一則，id 必須與輸入一致）：
{{"translations": [{{"id": 0, "title_zh": "..."}}]}}"""


def _build_messages(batch: list[dict]) -> list[dict]:
    payload = json.dumps(
        [{"id": i, "title": it["title"]} for i, it in enumerate(batch)],
        ensure_ascii=False,
        indent=2,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(count=len(batch), payload=payload)},
    ]


def _parse_response(text: str, batch_size: int) -> dict[int, dict]:
    """把模型回覆解析成 {id: {title_zh}}，解析失敗回傳空 dict。"""
    text = text.strip()
    # 防禦性處理：有些模型會包 markdown code fence
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}

    translations = data.get("translations", data if isinstance(data, list) else [])
    result: dict[int, dict] = {}
    for t in translations:
        if not isinstance(t, dict):
            continue
        idx = t.get("id")
        if isinstance(idx, int) and 0 <= idx < batch_size:
            result[idx] = {"title_zh": str(t.get("title_zh", "")).strip()}
    return result


def translate_items(
    items: list[dict],
    client,
    model: str = "gpt-4o-mini",
    batch_size: int = BATCH_SIZE,
    on_progress=None,
) -> list[dict]:
    """批次翻譯標題。回傳新的 dict 清單，每則多出 title_zh 欄位。

    client 是 openai.OpenAI 的實例（測試時可注入假的 client）。
    單一批次失敗會重試一次，再失敗就把該批標記為翻譯失敗，不中斷整體流程。
    """
    results: list[dict] = []
    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    for bi, batch in enumerate(batches):
        if on_progress:
            on_progress(bi, len(batches))

        translated: dict[int, dict] = {}
        last_err = ""
        for _attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=_build_messages(batch),
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                translated = _parse_response(resp.choices[0].message.content or "", len(batch))
                if translated:
                    break
                last_err = "回覆的 JSON 無法解析"
            except Exception as e:
                last_err = str(e)

        for i, it in enumerate(batch):
            t = translated.get(i, {})
            out = dict(it)
            out["title_zh"] = t.get("title_zh") or f"（翻譯失敗：{last_err}）"
            results.append(out)

    if on_progress:
        on_progress(len(batches), len(batches))
    return results
