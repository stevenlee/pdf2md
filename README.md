# pdf2md: High-Fidelity PDF to Markdown Converter

這是一個專為 USPTO 專利說明書與 arXiv 論文設計的 PDF / 圖片轉 Markdown 工具。核心目標是先用 Marker 做穩定的 PDF 物理萃取，再用 Vision LLM 對圖片、圖表、表格與混合文件頁做語意增強。

## 快速開始（遠端 GPU / DGX）

平常只會用到這幾步：

```bash
# 1. 首次設定：複製範本並填入遠端伺服器資訊
cp .env.example .env
#    編輯 .env，至少填 REMOTE_USER / REMOTE_HOST（REMOTE_DIR 預設 ~/pdf2md 即可）
#    建議先設定 SSH 免密碼登入到該伺服器

# 2. 把要轉的 PDF 放進輸入資料夾
cp 你的檔案.pdf pdf2mdVault/input_dir/

# 3. 執行（就這一行，跟以前一樣）
./remote_run.sh
```

執行中會顯示單行進度：**階段、已處理張數/總數、百分比、已用時間、預估剩餘（ETA）**。跑完後，Markdown 與圖片會在 `pdf2mdVault/output_dir/`，用 Obsidian 打開 `pdf2mdVault` 即可閱讀。

三個子命令：

```bash
./remote_run.sh          # 啟動新轉換並監看進度
./remote_run.sh status   # 監看目前這輪的進度/ETA，跑完會自動收割
./remote_run.sh stop     # 停掉遠端轉換並清除暫存，之後可重跑
```

> **可以安全地 `Ctrl-C` 離開**——只會停掉本機監看，遠端會繼續跑。想再看進度就用 `./remote_run.sh status` 接回；它會顯示目前進度，並在完成時自動把成果收割回本地。細節見「[遠端執行](#遠端執行) → 斷線韌性」。

常用選項（在指令前面加環境變數即可，詳見「[遠端環境變數](#遠端環境變數)」）：

```bash
FORCE=1 ./remote_run.sh          # 強制重轉（即使輸出已存在）
CLEAN_REMOTE=1 ./remote_run.sh   # 收割後清空遠端暫存
```

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

推薦使用遠端 GPU / DGX。設定好 `.env`（見下方）並把 PDF 放進 `pdf2mdVault/input_dir/` 後，執行：

```bash
./remote_run.sh
```

`./remote_run.sh`（= `run`）會：

1. 檢查遠端是否已有轉換在跑；若有，會拒絕並提示改用 `status` / `stop`（避免重跑殺掉進行中的容器）。
2. 同步程式碼到遠端，但排除 `input_dir`、`output_dir`、`.cache`、`logs`。
3. 單獨同步 `pdf2mdVault/input_dir` 到遠端，並清理殘留的 stale 容器與哨兵檔。
4. **以 detach 模式在遠端 Docker 內啟動轉換**（`remote_worker.sh`），然後在本機**輪詢顯示進度與 ETA**。
5. 完成後將遠端 `pdf2mdVault/output_dir` 回收到本機。
6. 若未設定 `KEEP_RAW=1`，清除本機 stale `*_raw.md`。

### 斷線韌性（重要）

轉換以 `setsid + nohup` 在遠端背景執行，**與你的 SSH 連線解耦**：

- **本機想中途離開**：直接 `Ctrl-C` 是安全的——只會停掉本機監看，遠端作業不受影響。
- **執行途中 SSH 斷線 / 關掉終端機**：遠端會繼續跑到完成。用 `./remote_run.sh status` 重新接回監看；它會顯示目前進度，並在偵測到完成時自動收割成果回本地。
- **想知道現在還在不在跑**：`./remote_run.sh status`。有容器在跑會顯示即時進度；已完成會直接收割；什麼都沒有會告訴你「無進行中的轉換」。
- **想中止並重跑**：`./remote_run.sh stop`（停容器 + 清哨兵檔），再 `./remote_run.sh`。
- **輸出檔權限**：容器結束時（含中斷）會自動把輸出 `chown` 回遠端使用者；萬一容器被強制 kill，清理階段會用一次性 root 容器強制清除，不會再出現 `Permission denied`。

每次 `run` 都會保存完整終端輸出，並在收割時把遠端即時 log 一併撈回：

```text
logs/remote_run_YYYYMMDD_HHMMSS.log      # 本機監看輸出
logs/remote_worker_YYYYMMDD_HHMMSS.log   # 遠端容器完整 log (收割時撈回)
```

> 遠端執行期間，狀態記錄在遠端 `~/pdf2md/` 下的哨兵檔：`.pdf2md_run.log`（即時 log）、`.pdf2md_run.done`（完成碼）、`.pdf2md_run.start`（啟動時間）。三者在收割完成或 `stop` 時會自動清除。

## 遠端環境變數

可在執行時臨時覆蓋：

```bash
FORCE=1 ./remote_run.sh
KEEP_RAW=1 ./remote_run.sh
WORKERS=2 ./remote_run.sh
CLEAN_REMOTE=1 ./remote_run.sh
POLL_INTERVAL=30 ./remote_run.sh
```

- `FORCE=1`：強制重轉已存在輸出。
- `KEEP_RAW=1`：保留 `*_raw.md` 參考檔。
- `WORKERS=2`：同時處理 2 個輸入檔。單 GPU 建議維持 1。
- `CLEAN_REMOTE=1`：成果回收後清空遠端 input/output。
- `POLL_INTERVAL=30`：本機輪詢遠端進度的間隔秒數（預設 15）。

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
