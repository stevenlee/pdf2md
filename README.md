# pdf2md: High-Fidelity PDF to Markdown Converter

這是一個專為 USPTO 專利說明書與 arXiv 論文設計的 PDF 轉 Markdown 工具。

## 🚀 核心設計：非同步雙階段管線
本專案採用「解耦」架構，解決了傳統 OCR 流程中 LLM 阻塞的問題：
1. **第一階段：物理萃取** (marker-pdf) - 高速解析文字、公式與圖片，產出 `_raw.md`。
2. **第二階段：語意增強** (Async Enhancer) - **並發**呼叫 LLM 將圖表轉換為 Mermaid 語法。

## 🛠 雙軌執行模式

### 模式 A：遠端加速 (推薦)
利用 NVIDIA DGX 或具備 GPU 的伺服器進行極速轉換。
```bash
./remote_run.sh
```
*   **自動化流程**：同步代碼 -> 伺服器 Docker 運算 -> 成品回傳至 `pdf2mdVault/output_dir`。
*   **技術優化**：預設開啟 GPU 穿透、4GB 共享記憶體、以及 `/tmp/pdf2md_cache` 模型持久化快取。

### 模式 B：本機執行 (輕量)
適合處理少量檔案。
```bash
./start.sh
```

## 📂 Obsidian Vault 整合管理
專案採用 **`pdf2mdVault`** 作為核心數據目錄，您可以直接用 Obsidian 打開此資料夾。
- **`input_dir/`**: 放置待轉換的 PDF。
- **`output_dir/`**: 輸出的 Markdown 與圖片（支援 Mermaid 語法）。
- **Git 友好**：已設定 `.gitkeep` 確保目錄結構被追蹤，但大檔案會被 `.gitignore` 自動跳過。

## ⚙️ 配置 (.env)
將 `.env.example` 複製為 `.env` 並填入：
- `OLLAMA_API_BASE`: 指向您的 Ollama 服務路徑。
- `OLLAMA_MODEL_VISION`: 建議使用 `gemma4:e4b` (速度快) 或 `gemma4:26b` (精準)。
- `REMOTE_HOST`: 遠端伺服器 IP (用於 `remote_run.sh`)。

## ⚙️ 遠端伺服器要求
- 支援 NVIDIA GPU 與 Docker。
- 已安裝 `nvidia-container-toolkit`。
- 建議設定 SSH 免密碼登入。
