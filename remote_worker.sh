#!/bin/bash
# 在 DGX host 上執行（由 remote_run.sh 以 detach 模式啟動）。
#
# 目的：讓轉換與「發起端的 SSH 連線」解耦——
#   1. 本腳本被 setsid + nohup 啟動，SSH 斷線不會中止它，容器會一路跑完。
#   2. 容器內掛 EXIT trap：無論正常結束或被中斷，都會把輸出/輸入目錄 chown 回
#      宿主使用者，讓 host 端能正常讀取/刪除（避免 root 檔造成 Permission denied）。
#   3. 結束後把 exit code 寫入 DONE_FILE，供 remote_run.sh 輪詢判斷完成與否。
#
# 用法: remote_worker.sh INPUT_DIR OUTPUT_DIR WORKERS FORCE_FLAG RAW_FLAG DONE_FILE
set -u

INPUT_DIR="$1"
OUTPUT_DIR="$2"
WORKERS="$3"
FORCE_FLAG="$4"   # "--force" 或 ""
RAW_FLAG="$5"     # "--keep-raw" 或 "--no-keep-raw"
DONE_FILE="$6"

# 以 DGX 上「執行本腳本的使用者」為準，容器結束時 chown 回這個 uid/gid。
HOST_UID=$(id -u)
HOST_GID=$(id -g)

rm -f "$DONE_FILE"

# -T: 不配置 pseudo-TTY (detach/nohup 下沒有 TTY)。
# 容器內先掛 trap 再跑轉換：trap 於容器 shell EXIT 時觸發，正常/中斷皆會 chown。
docker compose run --rm -T \
    -e HOST_UID="$HOST_UID" -e HOST_GID="$HOST_GID" \
    pdf2md bash -c '
        trap "chown -R $HOST_UID:$HOST_GID \"$1\" \"$2\" 2>/dev/null || true" EXIT
        python3 -m src.cli --input "$1" --output "$2" --workers "$3" $4 $5
    ' _ "$INPUT_DIR" "$OUTPUT_DIR" "$WORKERS" "$FORCE_FLAG" "$RAW_FLAG"
rc=$?

echo "$rc" > "$DONE_FILE"
exit "$rc"
