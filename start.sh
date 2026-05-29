#!/bin/bash

# 1. 載入 .env 配置
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    # 如果沒有 .env，則建立預設值
    echo "LLM_PROVIDER=ollama" > .env
    echo "OLLAMA_API_BASE=http://192.168.1.103:11434/v1" >> .env
    echo "INPUT_DIR=pdf2mdVault/input_dir" >> .env
    echo "OUTPUT_DIR=pdf2mdVault/output_dir" >> .env
    INPUT_DIR="pdf2mdVault/input_dir"
    OUTPUT_DIR="pdf2mdVault/output_dir"
fi

# 2. 建立目錄
mkdir -p "$INPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# 設定目錄
VENV_DIR="./venv"

echo "🚀 啟動 pdf2md 轉換工具..."

# 1. 檢查虛擬環境
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 正在建立虛擬環境..."
    python3 -m venv "$VENV_DIR"
fi

# 2. 啟用虛擬環境
source "$VENV_DIR/bin/activate"

# 3. 安裝/更新依賴
echo -n "🛠️ 正在優化本地依賴環境..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo " [完成]"

# 4. 檢查環境變數設定
if [ ! -f ".env" ]; then
    echo "📝 找不到 .env 檔案，正在從範本建立..."
    cp .env.example .env
    echo "⚠️  請記得編輯 .env 檔案來設定您的 LLM API (如 Ollama 或 Gemini)！"
fi

# 5. 確保輸入與輸出目錄存在
mkdir -p "$INPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# 6. 檢查輸入目錄是否有檔案
pdf_count=$(ls "$INPUT_DIR"/*.pdf 2>/dev/null | wc -l)
if [ "$pdf_count" -eq 0 ]; then
    echo "📁 已建立目錄。請將您的 PDF 檔案放入 $INPUT_DIR 目錄。"
    echo "ℹ️  放好檔案後，再次執行此腳本即可開始轉換。"
    exit 0
fi

# 7. 執行轉換
echo "🎯 找到 $pdf_count 個 PDF，開始批次轉換..."
# 強制使用 CPU 模式以避免 Mac MPS 死鎖問題
export TORCH_DEVICE=cpu
export PYTORCH_ENABLE_MPS_FALLBACK=1

# 啟用 Mac GPU (MPS) 加速
# export TORCH_DEVICE=mps
# export PYTORCH_ENABLE_MPS_FALLBACK=1

python -m src.cli --input "$INPUT_DIR" --output "$OUTPUT_DIR" --workers 2 --no-keep-raw

echo "✅ 轉換完成！請查看 $OUTPUT_DIR 目錄。"
