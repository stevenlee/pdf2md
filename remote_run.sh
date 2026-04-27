#!/bin/bash

# 載入 .env 變數
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ 找不到 .env 檔案，請確保設定正確。"
    exit 1
fi

# 檢查必要變數
if [ -z "$REMOTE_USER" ] || [ -z "$REMOTE_HOST" ] || [ -z "$REMOTE_DIR" ] || [ -z "$INPUT_DIR" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "❌ .env 中缺少必要設定。"
    exit 1
fi

LOCAL_DIR=$(pwd)

# 確保本地目錄存在
mkdir -p "$LOCAL_DIR/$INPUT_DIR"
mkdir -p "$LOCAL_DIR/$OUTPUT_DIR"

echo "🚀 [1/3] 同步代碼與 Vault 檔案到 DGX ($REMOTE_HOST)..."
# 同步整份專案，包含新的 Vault 結構
rsync -avz --delete --exclude 'venv' --exclude '__pycache__' --exclude '.git' "$LOCAL_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

echo "⚙️ [2/3] 在 DGX 上執行高效能轉換..."
# 將本地的路徑變數傳遞給 Docker 內部的 CLI
ssh "$REMOTE_USER@$REMOTE_HOST" "cd $REMOTE_DIR && docker compose run --rm pdf2md python3 -m src.cli --input $INPUT_DIR --output $OUTPUT_DIR --workers 1 --force"

echo "📥 [3/3] 將成果收割回本地 $OUTPUT_DIR..."
rsync -avz "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/$OUTPUT_DIR/" "$LOCAL_DIR/$OUTPUT_DIR/"

echo "✅ 全部完成！請在 Obsidian 中打開 pdf2mdVault 資料夾查看成果。"
