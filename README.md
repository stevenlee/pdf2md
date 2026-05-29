# pdf2md: High-Fidelity PDF to Markdown Converter

這是一個專為 USPTO 專利說明書與 arXiv 論文設計的 PDF 轉 Markdown 工具。

## 🚀 核心設計：語意增強管線
本專案採用「解耦」架構，解決了傳統 OCR 流程中 LLM 阻塞的問題，並導入智慧型圖片分類路由：

1. **第一階段：物理萃取** (marker-pdf) - 高速解析 PDF 文字、公式與圖片，產生暫存 `_raw.md`。
2. **第二階段：語意增強** (Async Enhancer) - **並發**處理圖片內容：
    *   **智慧分類**：先由 Vision LLM 判斷圖片類型（表格 / 文件表單 / 圖表 / 其他）。
    *   **精準路由**：根據分類結果呼叫對應的轉換管道（Markdown Table OCR / 文件表單轉文字 / Mermaid 轉換）。

## ✨ 特色功能：三階段圖片處理流程

為了提升轉換精確度，系統會對每一張圖片進行三階段處理：

### 1. 圖片類型辨識 (Classification)
利用 Vision 模型將圖片分類為以下類型：
- **TABLE**：純數據表格，路由至表格 OCR 管道。
- **DOCUMENT**：文件、申請書、合約等混合內容（標題、文字、表格、勾選框），路由至文件 OCR 管道。
- **DIAGRAM**：流程圖、架構圖，路由至 Mermaid 轉換管道。
- **OTHER**：一般照片或插圖，保留原始圖片路徑。

### 2. 混合內容處理 (Document OCR)
針對「標題 + 文字 + 表格」的複雜表單（如投資開戶書、租賃合約）：
- **完整轉錄**：保留標題、段落、清單。
- **表格還原**：自動辨識並轉換頁面中的表格部分。
- **勾選框識別**：精準呈現 ☑ (Checked) 與 ☐ (Unchecked) 狀態。

### 3. Mermaid 穩定性強化
針對圖表轉換，提供工業級的穩定性：
- **自動重試機制**：若 LLM 生成語法錯誤，會自動嘗試修復並重試（最多 2 次）。
- **語法驗證與修正**：自動修復未閉合括號、移除多餘分號、校正圖表類型宣告。
- **智慧標籤優化**：強制標籤雙引號包覆，支援包含括號的複雜文字（如 `A["Step (S100)"]`）。

## 🛠 雙軌執行模式

### 模式 A：遠端加速 (推薦)
利用 NVIDIA DGX 或具備 GPU 的伺服器進行極速轉換。
```bash
./remote_run.sh
```
*   **自動化流程**：同步代碼與輸入檔 -> 伺服器 Docker 運算 -> 成品回傳至 `pdf2mdVault/output_dir`。
*   **技術優化**：預設開啟 GPU 穿透、4GB 共享記憶體、以及 `.cache/pdf2md` 模型持久化快取。

### 模式 B：本機執行 (輕量)
適合處理少量檔案。
```bash
./start.sh
```

## 📂 Obsidian Vault 整合管理
專案採用 **`pdf2mdVault`** 作為核心數據目錄，您可以直接用 Obsidian 打開此資料夾。

## ⚙️ CLI 參數說明
- `--mermaid / --no-mermaid`: 是否將圖表轉為 Mermaid (預設開啟)。
- `--tables / --no-tables`: 是否將表格/文件轉為 Markdown (預設開啟)。
- `--workers`: 並行處理的執行緒數量。
- `--force`: 強制重新轉換已存在的檔案。
- `--keep-raw / --no-keep-raw`: 是否保留第一階段產生的 `*_raw.md` 參考檔，預設不保留。

## ⚙️ 遠端執行環境變數
`remote_run.sh` 可用環境變數微調行為：
- `FORCE=1 ./remote_run.sh`: 強制重新轉換所有輸入檔。
- `KEEP_RAW=1 ./remote_run.sh`: 保留 `*_raw.md` 參考檔。
- `WORKERS=2 ./remote_run.sh`: 調整遠端轉換 workers。

每次遠端執行會把完整終端輸出保存到 `logs/remote_run_*.log`，方便追查偶發轉檔失敗。

## ⚙️ Vision/OCR 穩定性
大份專利可能包含數十張圖片；即使 `workers=1`，圖片 OCR 仍會並發呼叫模型。可在 `.env` 調整：
- `VISION_MAX_CONCURRENCY=2`: 單份文件內同時送出的 vision/OCR 請求上限。
- `VISION_REQUEST_TIMEOUT=180`: 單次 vision/OCR API timeout 秒數。
- `VISION_REQUEST_RETRIES=2`: timeout 或 5xx/429 等暫時性錯誤的重試次數。

## ⚙️ 配置 (.env)
將 `.env.example` 複製為 `.env` 並填入：
- `OLLAMA_API_BASE`: 指向您的 Ollama 服務路徑。
- `OLLAMA_MODEL_VISION`: 建議使用 `gemma4:e4b` (速度快) 或 `gemma4:26b` (精準)。
- `REMOTE_HOST`: 遠端伺服器 IP (用於 `remote_run.sh`)。

## ⚙️ 遠端伺服器要求
- 支援 NVIDIA GPU 與 Docker。
- 已安裝 `nvidia-container-toolkit`。
- 建議設定 SSH 免密碼登入。
