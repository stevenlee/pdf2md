# PDF2MD 系統架構設計與實作報告 (Final)

## 1. 專案目標
本專案成功建構了一個高效能、非同步的 PDF 轉 Markdown 系統，專門處理 USPTO 專利與 arXiv 論文。系統核心在於將「物理內容萃取」與「語意圖表解析」解耦，並利用遠端 DGX (Grace Blackwell) 伺服器進行算力加速。

---

## 2. 實作架構 (As-Built)

系統採用「雙軌執行、兩階段處理」的現代化架構。

### 2.1 兩階段非同步流水線 (Two-Stage Async Pipeline)
*   **Stage 1: 物理基底萃取 (Physical Extraction)**
    *   **組件**：`src/converter.py` (基於 Marker-pdf)
    *   **行為**：純本地運算，專注於 OCR、版面分析與圖片切割。
    *   **產出**：`_raw.md` 原型檔與物理圖片。
*   **Stage 2: 語意增強與並發轉換 (Semantic Enhancement)**
    *   **組件**：`src/enhancer.py` (Asyncio + aiohttp)
    *   **行為**：使用 `asyncio.gather` 並發呼叫遠端 Ollama (Gemma 4:e4b/26b) 視覺模型。
    *   **核心技術**：
        *   **非同步並發**：多張圖片同時進行 VLM 轉換，消除序列等待。
        *   **語法硬化**：自動為 Mermaid 節點添加雙引號並清理嵌套標籤。
        *   **後處理**：LaTeX 正則化與雜質清理。

### 2.2 遠端自動化流水線 (Remote Automation)
透過 `remote_run.sh` 實現了本機開發、遠端運算的無縫體驗：
1.  **碼同步 (Sync)**：利用 `rsync --delete` 確保本機代碼與 Vault 結構完整鏡像至 DGX。
2.  **Docker 執行 (Execute)**：在伺服器端利用 NVIDIA GPU 進行運算，並透過 Volume 映射持久化模型快取。
3.  **成果收割 (Harvest)**：運算結束後自動將 `output_dir` 內容回傳至本機。

### 2.3 Obsidian Vault 整合
*   系統目錄結構完全相容於 Obsidian。
*   使用 `.gitkeep` 技術保留目錄結構，同時透過 `.gitignore` 確保大型 PDF 與 API 金鑰不外流。

---

## 3. 技術規格與優化 (Optimization)

### 3.1 模型快取機制 (Model Caching)
*   **路徑**：`/tmp/pdf2md_cache`
*   **實作**：在 `docker-compose.yml` 中強制指定 `HF_HOME` 與 `MARKER_DATA_DIR`。
*   **效益**：模型下載一次後永久保存，啟動時間從數分鐘縮短至秒級。

### 3.2 效能監控
*   **計時功能**：`src/cli.py` 整合了 `time.time()` 統計。
*   **指標**：提供 S1 (物理) 與 S2 (語意) 分別的執行秒數，便於評估模型與算力環境。

### 3.3 錯誤容忍 (Resilience)
*   **異常捕捉**：`llm_client` 強化了 HTTP 錯誤的拋出機制。
*   **優雅降級**：若圖表轉換失敗，系統自動回退至原始圖片連結，確保文件內容不遺漏。

---

## 4. 結論
透過本次重構，系統從一個容易死鎖、難以擴展的腳本，轉型為一個具備生產力的自動化工具。
