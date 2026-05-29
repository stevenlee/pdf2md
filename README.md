# pdf2md: High-Fidelity PDF to Markdown Converter

這是一個專為 USPTO 專利說明書與 arXiv 論文設計的 PDF / 圖片轉 Markdown 工具。核心目標是先用 Marker 做穩定的 PDF 物理萃取，再用 Vision LLM 對圖片、圖表、表格與混合文件頁做語意增強。

## 核心流程

1. **物理萃取**：Marker 解析 PDF 文字、公式與圖片，產生暫存 `*_raw.md` 與圖片目錄。
2. **智慧圖片增強**：每張圖片以 `vision_smart_convert.md` 單次呼叫完成「分類 + 轉換」，輸出 `TYPE: TABLE / DOCUMENT / DIAGRAM / OTHER` 與對應內容。
3. **降級與清理**：表格/文件轉 Markdown，圖表轉 Mermaid；若 Mermaid 無效，會重試並降級為 OCR 文字 + 原圖。預設不保留 `*_raw.md`。

## 圖片類型

- **TABLE**：純表格，轉為 GitHub-Flavored Markdown table。
- **DOCUMENT**：表單、合約、混合頁面，保留標題、段落、表格與 checkbox。
- **DIAGRAM**：流程圖、架構圖、狀態圖等，轉為 Mermaid。
- **OTHER**：照片、統計圖、無法可靠結構化的圖片，保留原圖連結。

## Mermaid 穩定性

圖表轉換會做二次修復與驗證：

- 節點標籤自動補雙引號，例如 `A["Step (S100)"]`。
- 巢狀雙引號會改成單引號，避免 Mermaid 語法破裂。
- 支援節點、管線邊標籤與 link 邊標籤的狀態機修復。
- 無效 Mermaid 會重試；仍失敗時保留原圖並嘗試 OCR 抽出可讀文字。

## 遠端執行

推薦使用遠端 GPU / DGX：

```bash
./remote_run.sh
```

腳本會：

1. 同步程式碼到遠端，但排除 `input_dir`、`output_dir`、`.cache`、`logs`。
2. 單獨同步 `pdf2mdVault/input_dir` 到遠端。
3. 在 Docker 內執行轉換。
4. 將遠端 `pdf2mdVault/output_dir` 回收到本機。
5. 若未設定 `KEEP_RAW=1`，清除本機 stale `*_raw.md`。

每次遠端執行都會保存完整終端輸出：

```text
logs/remote_run_YYYYMMDD_HHMMSS.log
```

## 遠端環境變數

可在執行時臨時覆蓋：

```bash
FORCE=1 ./remote_run.sh
KEEP_RAW=1 ./remote_run.sh
WORKERS=2 ./remote_run.sh
CLEAN_REMOTE=1 ./remote_run.sh
```

- `FORCE=1`：強制重轉已存在輸出。
- `KEEP_RAW=1`：保留 `*_raw.md` 參考檔。
- `WORKERS=2`：同時處理 2 個輸入檔。單 GPU 建議維持 1。
- `CLEAN_REMOTE=1`：成果回收後清空遠端 input/output。

## 本機執行

```bash
./start.sh
```

本機模式適合少量檔案，預設使用 CPU 以避開 Mac MPS 死鎖問題。

## CLI 參數

```bash
python -m src.cli --input pdf2mdVault/input_dir --output pdf2mdVault/output_dir
```

- `--mermaid / --no-mermaid`：是否嘗試將圖表轉 Mermaid，預設開啟。
- `--tables / --no-tables`：是否嘗試將表格/文件轉 Markdown，預設開啟。
- `--workers`：同時處理的檔案數。有效 vision 併發約為 `workers × VISION_MAX_CONCURRENCY`。
- `--force`：強制重新轉換已存在的檔案。
- `--keep-raw / --no-keep-raw`：是否保留 `*_raw.md`，預設不保留。

## 模型設定

`.env` 可覆蓋模型角色：

- `OLLAMA_MODEL_TEXT`：純文字任務。
- `OLLAMA_MODEL_VISION`：舊式圖表/vision 任務與部分降級用途。
- `OLLAMA_MODEL_OCR`：文件 OCR / Mermaid 失敗降級。
- `OLLAMA_MODEL_SMART`：單次「分類 + 轉換」圖片處理，預設 `gemma4:26b`。

速度與品質取捨：

- `gemma4:26b`：較準，適合複雜專利圖。
- `gemma4:e4b`：較快，適合簡單圖或快速草稿，但可能漏節點。

## Vision / OCR 穩定性

可在 `.env` 調整：

- `VISION_MAX_CONCURRENCY=2`：單份文件內同時送出的 vision/OCR 請求上限。
- `VISION_REQUEST_TIMEOUT=600`：單次 vision/OCR API timeout 秒數。
- `VISION_REQUEST_RETRIES=2`：timeout、429、5xx 等暫時性錯誤的重試次數。

## Cache 與資料目錄

- `pdf2mdVault/input_dir`：放 PDF / 圖片輸入。
- `pdf2mdVault/output_dir`：Markdown 輸出與圖片資產。
- `.cache/pdf2md`：遠端 Docker 掛載的 Marker / Surya / Hugging Face cache，避免重複下載模型。
- `logs/`：遠端執行紀錄。

`pdf2mdVault`、`.cache`、`logs` 預設不提交到 Git。

## 遠端伺服器要求

- 支援 NVIDIA GPU 與 Docker。
- 已安裝 `nvidia-container-toolkit`。
- 已部署 Ollama / vLLM 服務並可由容器連線。
- 建議設定 SSH 免密碼登入。

## 測試

```bash
venv/bin/python -m unittest tests.test_enhancer
venv/bin/python -m py_compile src/config.py src/converter.py src/enhancer.py src/llm_client.py src/cli.py src/processor.py
bash -n remote_run.sh start.sh
```
