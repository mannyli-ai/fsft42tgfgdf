# Techmeme Lite

GitHub Actions 每 6 小時自動收集 Techmeme 新聞存進這個 repo，
Streamlit app 讀取收集好的資料，用 OpenAI 翻譯成台灣繁體中文，輸出 CSV。

## 架構

Techmeme 會擋雲端主機直接爬它的網頁（Streamlit Cloud 抓 archive 頁會 403），
但 RSS feed（feed.xml）是給訂閱器抓的端點。這個專案用 GitHub Actions
定時抓 feed，把新項目存成 `data/YYYY-MM-DD.json`，等於自建一份免費的
RSS 歷史備份（取代 Feedbin 的角色）。app 完全不連 techmeme.com，
只讀 repo 裡的資料，所以不會被擋。

RSS feed 涵蓋約一天半的內容，每 6 小時收集一次有很大的安全邊際。
資料從 collector 開始運作那天起累積，日期想選多久的區間都行。

## 部署步驟

1. 把這個資料夾推上 GitHub（檔案要在 repo 根目錄，包含 `.github` 資料夾）
2. 到 repo 的 **Actions** 分頁。如果看到啟用提示就按啟用，
   然後選左側 **Collect Techmeme RSS**，按 **Run workflow** 手動跑第一次。
   跑完 `data/` 目錄會出現最近一兩天的資料
3. 到 https://share.streamlit.io 建 app，選這個 repo，主檔案填 `app.py`
4. （可選）在 app 的 Settings → Secrets 加 `OPENAI_API_KEY = "sk-..."`
   就不用每次輸入金鑰

之後 Actions 每 6 小時自動收集，Streamlit Cloud 會在 repo 有新 commit 時
自動同步，不需要任何手動維護。

## 使用流程

1. 側邊欄選日期區間（只能選有資料的範圍；上限 31 天）
2. 按「載入」，預覽新聞。這一步免費
3. 輸入 OpenAI API key（或已設 secrets），按「開始翻譯」
4. 下載 CSV（utf-8-sig 編碼，Excel 直接開不會亂碼）

CSV 欄位：日期、原始標題、原始摘要、翻譯標題、翻譯摘要、原文連結、Techmeme 連結。
不需要日期欄的話，把 `app.py` 裡 `CSV_COLUMNS` 的 `"date"` 那行刪掉即可。

## 注意事項

- Techmeme 以美東時間換日，「原始摘要」是 Techmeme 附的原文開頭節錄
- GitHub 對閒置 repo 會在 60 天後停用排程 workflow，收到通知信時
  到 Actions 分頁按一下 enable 即可恢復（workflow 自己的 commit 通常會維持活躍）
- 若 Actions 執行失敗，GitHub 會寄信通知；到 Actions 分頁看 log，
  最可能的原因是 Techmeme feed 暫時無法連線，下一輪會自動重試

## 本機開發

```bash
pip install -r requirements.txt
python collector.py      # 抓一次 feed，建立 data/
streamlit run app.py
```

## 測試

```bash
pip install pytest
python -m pytest tests/ -v
```

25 個測試涵蓋：feed 解析（含真實 feed 結構、截斷 XML、重複 guid、
缺外站連結）、追蹤參數清理、collector 合併與冪等性、損壞檔案復原、
抓取重試、資料讀取與缺日警告、批次翻譯、JSON 容錯、完整 UI 流程、CSV 編碼。
