#!/bin/bash
set -euo pipefail

if [ -z "${REMOTE_RUN_LOG_ACTIVE:-}" ]; then
    LOCAL_DIR=$(pwd)
    LOG_DIR="${LOG_DIR:-$LOCAL_DIR/logs}"
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/remote_run_$(date +%Y%m%d_%H%M%S).log"
    echo "📝 本次執行紀錄: $LOG_FILE"
    REMOTE_RUN_LOG_ACTIVE=1 LOG_FILE="$LOG_FILE" bash "$0" "$@" 2>&1 | tee -a "$LOG_FILE"
    exit "${PIPESTATUS[0]}"
fi

# 載入 .env 變數
if [ -f .env ]; then
    set -a
    source .env
    set +a
else
    echo "❌ 找不到 .env 檔案，請確保設定正確。"
    exit 1
fi

# 檢查必要變數
if [ -z "${REMOTE_USER:-}" ] || [ -z "${REMOTE_HOST:-}" ] || [ -z "${REMOTE_DIR:-}" ] || [ -z "${INPUT_DIR:-}" ] || [ -z "${OUTPUT_DIR:-}" ]; then
    echo "❌ .env 中缺少必要設定。"
    exit 1
fi

LOCAL_DIR=$(pwd)

# Sourcing .env expands REMOTE_DIR=~/pdf2md against the local machine.
# Convert that back to a remote-home path before using ssh/rsync targets.
if [[ "$REMOTE_DIR" == "$HOME/"* ]]; then
    REMOTE_DIR="~/${REMOTE_DIR#"$HOME"/}"
fi

WORKERS="${WORKERS:-1}"
FORCE="${FORCE:-0}"
KEEP_RAW="${KEEP_RAW:-0}"

if [ "$FORCE" = "1" ] || [ "$FORCE" = "true" ]; then
    FORCE_FLAG="--force"
else
    FORCE_FLAG=""
fi

if [ "$KEEP_RAW" = "1" ] || [ "$KEEP_RAW" = "true" ]; then
    RAW_FLAG="--keep-raw"
else
    RAW_FLAG="--no-keep-raw"
fi

# 確保本地目錄存在
mkdir -p "$LOCAL_DIR/$INPUT_DIR"
mkdir -p "$LOCAL_DIR/$OUTPUT_DIR"

echo "🚀 [1/4] 同步程式碼到 DGX ($REMOTE_HOST)..."
rsync -az --delete \
    --exclude 'venv' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.cache' \
    --exclude '.git' \
    --exclude '.DS_Store' \
    --exclude 'logs' \
    --exclude "$INPUT_DIR" \
    --exclude "$OUTPUT_DIR" \
    "$LOCAL_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

echo "📤 [2/4] 同步輸入檔案到遠端 $INPUT_DIR..."
ssh "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_DIR/$INPUT_DIR $REMOTE_DIR/$OUTPUT_DIR"
rsync -az --delete "$LOCAL_DIR/$INPUT_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/$INPUT_DIR/"

echo "⚙️ [3/4] 在 DGX 上執行高效能轉換..."
ssh "$REMOTE_USER@$REMOTE_HOST" "cd $REMOTE_DIR && docker compose run --rm pdf2md python3 -m src.cli --input $INPUT_DIR --output $OUTPUT_DIR --workers $WORKERS $FORCE_FLAG $RAW_FLAG"

echo "📥 [4/4] 將成果收割回本地 $OUTPUT_DIR..."
rsync -az "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/$OUTPUT_DIR/" "$LOCAL_DIR/$OUTPUT_DIR/"
if [ "$KEEP_RAW" != "1" ] && [ "$KEEP_RAW" != "true" ]; then
    find "$LOCAL_DIR/$OUTPUT_DIR" -name '*_raw.md' -delete
fi

echo "✅ 全部完成！請在 Obsidian 中打開 pdf2mdVault 資料夾查看成果。"
