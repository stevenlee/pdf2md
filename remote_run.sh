#!/bin/bash
set -euo pipefail

# 子命令: run (預設) | status | stop
CMD="${1:-run}"

# 只有 run 需要保存完整終端輸出；status/stop 直接在前景執行不另存 log。
if [ "$CMD" = "run" ] && [ -z "${REMOTE_RUN_LOG_ACTIVE:-}" ]; then
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
START_TS=$(date +%s)
RUN_TS=$(date +%Y%m%d_%H%M%S)

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

# SSH keepalive：減少長時間執行時的閒置斷線 (偵測到斷線也不會殺掉遠端 detach 的容器)。
SSH_OPTS="-o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ClearAllForwardings=yes"
POLL_INTERVAL="${POLL_INTERVAL:-15}"    # 本地輪詢遠端進度的間隔 (秒)
STARTUP_GRACE="${STARTUP_GRACE:-180}"   # 遠端未啟動的最長等待 (秒)，逾時判定失敗

RT="$REMOTE_USER@$REMOTE_HOST"

# 遠端 detach 執行用的哨兵檔 (相對 REMOTE_DIR)。
DONE_REL=".pdf2md_run.done"     # 內容為 worker 的 exit code
LOG_REL=".pdf2md_run.log"       # 即時 log
START_REL=".pdf2md_run.start"   # 啟動時的遠端 epoch，供計算真實已用時間
DONE_REMOTE="$REMOTE_DIR/$DONE_REL"
LOG_REMOTE="$REMOTE_DIR/$LOG_REL"
START_REMOTE="$REMOTE_DIR/$START_REL"

CONTAINER_FILTER="name=pdf2md-pdf2md-run-"

# --- 小工具 ---------------------------------------------------------------

# 秒數 → 1h02m03s
fmt() {
    local s=${1:-0}
    [ "$s" -lt 0 ] 2>/dev/null && s=0
    printf '%dh%02dm%02ds' $((s / 3600)) $(((s % 3600) / 60)) $((s % 60))
}

# 從單次輪詢輸出中依前綴取值
val() { printf '%s\n' "$POLL_OUT" | sed -n "s/^$1://p"; }

# 是否為非負整數
is_num() { case "${1:-}" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac }

# 一次 ssh 抓齊：容器狀態 / 進度計數 / 完成碼 / 遠端時間。失敗回傳非 0。
# TOTAL/DONEIMG 都只統計「最後一批 並發處理」(= 當前檔案)：DONEIMG 以 tac 取到
# 最後一批起點、再以不重複圖片名計數，避免跨檔累計與 DIAGRAM 重試造成的虛胖。
fetch_status() {
    POLL_OUT=$(ssh $SSH_OPTS "$RT" "
        cd $REMOTE_DIR 2>/dev/null || exit 0
        echo \"NOW:\$(date +%s)\"
        echo \"START:\$(cat '$START_REL' 2>/dev/null || true)\"
        echo \"RUNNING:\$(docker ps --filter '$CONTAINER_FILTER' -q 2>/dev/null | head -1)\"
        echo \"TOTAL:\$(grep -aoE '並發處理 [0-9]+ 張圖片' '$LOG_REL' 2>/dev/null | tail -1 | grep -aoE '[0-9]+' || true)\"
        echo \"NBATCH:\$(grep -acE '並發處理 [0-9]+ 張圖片' '$LOG_REL' 2>/dev/null || true)\"
        echo \"DONEIMG:\$(tac '$LOG_REL' 2>/dev/null | sed -n '1,/並發處理/p' | grep -ao '圖片 [^ ]* 分類結果' | sort -u | wc -l || true)\"
        echo \"FDONE:\$(grep -acE '完成(非同步增強|圖片增強)轉換' '$LOG_REL' 2>/dev/null || true)\"
        echo \"FTOTAL:\$(ls '$INPUT_DIR' 2>/dev/null | wc -l || true)\"
        echo \"STAGE1:\$(grep -acE '開始物理萃取' '$LOG_REL' 2>/dev/null || true)\"
        echo \"LAST:\$(grep -aE 'INFO:|Recognizing|Detecting|OCR Error|Traceback|Error' '$LOG_REL' 2>/dev/null | tail -1 | cut -c1-120 || true)\"
        echo \"RC:\$(cat '$DONE_REL' 2>/dev/null || true)\"
    " 2>/dev/null)
}

# 收割成果 + (選擇性) 清空遠端 + 清除哨兵檔
harvest_and_clean() {
    echo "📥 將成果收割回本地 $OUTPUT_DIR..."
    rsync -az -e "ssh $SSH_OPTS" "$RT:$REMOTE_DIR/$OUTPUT_DIR/" "$LOCAL_DIR/$OUTPUT_DIR/" || true
    if [ "$KEEP_RAW" != "1" ] && [ "$KEEP_RAW" != "true" ]; then
        find "$LOCAL_DIR/$OUTPUT_DIR" -name '*_raw.md' -delete
    fi

    # 保存遠端即時 log 到本地，供事後除錯 (刪除哨兵前先撈回)。
    rsync -az -e "ssh $SSH_OPTS" "$RT:$LOG_REMOTE" "$LOCAL_DIR/logs/remote_worker_${RUN_TS}.log" 2>/dev/null || true

    if [ "${CLEAN_REMOTE:-0}" = "1" ] || [ "${CLEAN_REMOTE:-0}" = "true" ]; then
        echo "🧹 清空遠端 $INPUT_DIR 與 $OUTPUT_DIR (收割已完成)..."
        # 一般刪除；若容器被 SIGKILL、trap 沒跑完而殘留 root 檔，用一次性 root 容器強制清除。
        # 清理失敗不應中止整體流程 (成果已收割)，故以 || true 包住。
        ssh $SSH_OPTS "$RT" "
            rm -rf $REMOTE_DIR/$INPUT_DIR/* $REMOTE_DIR/$OUTPUT_DIR/* 2>/dev/null
            if [ -n \"\$(ls -A $REMOTE_DIR/$OUTPUT_DIR 2>/dev/null)\" ] || [ -n \"\$(ls -A $REMOTE_DIR/$INPUT_DIR 2>/dev/null)\" ]; then
                echo '↳ 偵測到 root 殘留檔，改用 root 容器強制清除...'
                docker run --rm -v $REMOTE_DIR:/work alpine sh -c 'rm -rf /work/$INPUT_DIR/* /work/$OUTPUT_DIR/*'
            fi
        " || echo "⚠️  遠端清理未完全成功 (成果已收割，可稍後手動清理)。"
    fi

    # 清除本次哨兵檔
    ssh $SSH_OPTS "$RT" "rm -f $DONE_REMOTE $LOG_REMOTE $START_REMOTE" 2>/dev/null || true
}

# 監看遠端進度 (單行狀態 + ETA)；完成/異常後回收成果。回傳碼放進 SSH_RC。
# 參數: mode = run | status
monitor_and_harvest() {
    local mode="$1"
    local wait_start; wait_start=$(date +%s)
    local saw_running=0 gone=0 iter=0
    local eta_t0="" eta_c0="" eta_total="" last_elapsed=0
    SSH_RC=""

    while true; do
        if ! fetch_status; then
            echo "⚠️  輪詢連線暫時失敗，${POLL_INTERVAL}s 後重試 (遠端仍在執行)..."
            sleep "$POLL_INTERVAL"; continue
        fi
        iter=$((iter + 1))

        local now start start_raw running total doneimg stage1 last rc elapsed
        local nbatch fdone ftotal fileinfo
        now=$(val NOW);       is_num "$now"   || now=$(date +%s)
        start_raw=$(val START)
        start="$start_raw";   is_num "$start" || start="$now"
        running=$(val RUNNING)
        total=$(val TOTAL);   is_num "$total"     || total=0
        doneimg=$(val DONEIMG); is_num "$doneimg" || doneimg=0
        nbatch=$(val NBATCH); is_num "$nbatch" || nbatch=0
        fdone=$(val FDONE);   is_num "$fdone"  || fdone=0
        ftotal=$(val FTOTAL); is_num "$ftotal" || ftotal=0
        stage1=$(val STAGE1); is_num "$stage1" || stage1=0
        last=$(val LAST)
        rc=$(val RC)
        elapsed=$((now - start)); [ "$elapsed" -lt 0 ] && elapsed=0
        last_elapsed=$elapsed

        [ -n "$running" ] && { saw_running=1; gone=0; } || gone=$((gone + 1))

        # status 模式：首輪就沒有任何進行中跡象 → 立即回報，不必印「等待啟動」。
        if [ "$mode" = "status" ] && [ "$iter" = "1" ] \
           && [ -z "$running" ] && [ "$stage1" = "0" ] && [ "$total" = "0" ] && [ -z "$rc" ]; then
            echo "ℹ️  目前沒有偵測到進行中的轉換。"
            echo "   若要啟動新轉換： ./remote_run.sh"
            SSH_RC=""; return 0
        fi

        # --- 顯示進度 ---
        fileinfo=""
        if [ -n "$rc" ]; then
            :  # 已完成，下面統一處理
        elif [ "$stage1" -gt "$nbatch" ]; then
            # 已萃取檔數 > 已進入增強的檔數 → 下一個檔案的階段1進行中，
            # 此時 TOTAL/DONEIMG 還是上一個檔案的殘值，不能拿來顯示。
            [ "$ftotal" -gt 0 ] && fileinfo="檔案 $stage1/$ftotal | "
            printf '🔄 [階段1/2 物理萃取 Marker] %s已用 %s | %s\n' \
                "$fileinfo" "$(fmt "$elapsed")" "${last:-模型解析中…}"
        elif [ "$total" -gt 0 ]; then
            [ "$doneimg" -gt "$total" ] && doneimg=$total
            # 換檔案 (批次大小改變或計數回退) → 重設 ETA 取樣基準
            if [ "$total" != "$eta_total" ] || [ "$doneimg" -lt "${eta_c0:-0}" ]; then
                eta_t0=""; eta_c0=""; eta_total=$total
            fi
            local pct=$((doneimg * 100 / total))
            local eta="估算中"
            if [ -z "$eta_t0" ] && [ "$doneimg" -gt 0 ]; then eta_t0=$now; eta_c0=$doneimg; fi
            if [ -n "$eta_t0" ] && [ "$now" -gt "$eta_t0" ] && [ "$doneimg" -gt "${eta_c0:-0}" ]; then
                # 首選：接上監看後的即時速率 (最貼近目前吞吐)。
                local dc=$((doneimg - eta_c0)) dt=$((now - eta_t0))
                eta="~$(fmt $(((total - doneimg) * dt / dc)))"
            elif [ "$fdone" = "0" ] && [ "$doneimg" -gt 0 ] && [ "$elapsed" -gt 0 ]; then
                # 退而求其次：還沒有即時樣本時，用自啟動以來的平均速率給粗估
                # (僅第一個檔案適用；後續檔案的 elapsed 含前面檔案的時間，估了反而誤導)。
                eta="~$(fmt $(((total - doneimg) * elapsed / doneimg)))"
            fi
            if [ "$ftotal" -gt 0 ]; then
                local fcur=$((fdone + 1))
                [ "$fcur" -gt "$ftotal" ] && fcur=$ftotal
                fileinfo="檔案 $fcur/$ftotal | "
            fi
            printf '🔄 [階段2/2 圖片增強] %s本檔圖片 %d/%d (%d%%) | 已用 %s | 本檔預估剩餘 %s\n' \
                "$fileinfo" "$doneimg" "$total" "$pct" "$(fmt "$elapsed")" "$eta"
        elif [ "$stage1" -gt 0 ]; then
            printf '🔄 [階段1/2 物理萃取 Marker] 已用 %s | %s\n' "$(fmt "$elapsed")" "${last:-模型解析中…}"
        else
            printf '⏳ 等待遠端啟動轉換... 已等 %s\n' "$(fmt $(( $(date +%s) - wait_start )))"
        fi

        # --- 終止條件 ---
        if [ -n "$rc" ]; then
            # 只有配對的 .start 也存在時，.done 才視為「本輪的完成標記」。
            # 沒有 .start 的孤兒 done 是舊殘留 → 在 status 模式忽略，避免誤收割/誤清理。
            if [ "$mode" = "status" ] && [ -z "$start_raw" ] && [ -z "$running" ]; then
                echo "ℹ️  偵測到殘留的完成標記但無對應執行紀錄 (可能是舊檔)，予以忽略。"
                echo "   若要清除殘留： ./remote_run.sh stop"
                return 0
            fi
            SSH_RC="$rc"
            [ "$rc" = "0" ] && echo "✅ 遠端回報轉換完成 (exit=$rc)。" || echo "❌ 遠端回報轉換失敗 (exit=$rc)。"
            break
        fi
        # 容器已消失但沒有完成碼：連續兩輪確認 → 異常中止
        if [ "$saw_running" = "1" ] && [ "$gone" -ge 2 ]; then
            echo "❌ 遠端容器已結束但未寫出完成碼，判定為異常中止。"
            SSH_RC=1; break
        fi
        # 從未看到容器啟動且逾時 → worker 啟動失敗 (run 模式) / 無進行中 (status 模式)
        if [ "$saw_running" = "0" ] && [ "$stage1" = "0" ] && [ $(( $(date +%s) - wait_start )) -gt "$STARTUP_GRACE" ]; then
            if [ "$mode" = "status" ]; then
                echo "ℹ️  目前沒有偵測到進行中的轉換 (無容器、無進度)。"
                echo "   若要啟動新轉換： ./remote_run.sh"
                SSH_RC=""; return 0
            fi
            echo "❌ 遠端在 ${STARTUP_GRACE}s 內未啟動轉換 (worker 可能啟動失敗，可用 ./remote_run.sh status 檢查)。"
            SSH_RC=1; break
        fi

        sleep "$POLL_INTERVAL"
    done

    harvest_and_clean

    printf '⏱️  遠端執行耗時: %s — 完成時間 %s\n' "$(fmt "$last_elapsed")" "$(date '+%Y-%m-%d %H:%M:%S')"

    if [ -n "$SSH_RC" ] && [ "$SSH_RC" -ne 0 ]; then
        echo "❌ 轉換過程有錯誤或中斷 (Exit Code: $SSH_RC)，但已盡力收割已生成的成果。"
        return "$SSH_RC"
    fi
    echo "✅ 全部完成！請在 Obsidian 中打開 pdf2mdVault 資料夾查看成果。"
    return 0
}

# --- 子命令 ---------------------------------------------------------------

do_stop() {
    echo "🛑 停止遠端轉換並清除哨兵檔..."
    ssh $SSH_OPTS "$RT" "
        docker ps -a --filter '$CONTAINER_FILTER' -q | xargs -r docker rm -f
        rm -f $DONE_REMOTE $LOG_REMOTE $START_REMOTE
    " || true
    echo "✅ 已停止。可重新執行 ./remote_run.sh"
}

do_status() {
    echo "🔎 檢查遠端轉換狀態 ($REMOTE_HOST)..."
    monitor_and_harvest status
}

do_run() {
    # 防呆：若已有轉換在執行中，不要重複啟動 (重跑會殺掉正在跑的容器)。
    local active
    active=$(ssh $SSH_OPTS "$RT" "docker ps --filter '$CONTAINER_FILTER' -q 2>/dev/null | head -1" 2>/dev/null || true)
    if [ -n "$active" ]; then
        echo "⚠️  遠端已有轉換在執行中，未啟動新工作。"
        echo "   監看進度： ./remote_run.sh status"
        echo "   停止重跑： ./remote_run.sh stop && ./remote_run.sh"
        exit 1
    fi

    mkdir -p "$LOCAL_DIR/$INPUT_DIR"
    mkdir -p "$LOCAL_DIR/$OUTPUT_DIR"

    echo "🚀 [1/4] 同步程式碼到 DGX ($REMOTE_HOST)..."
    rsync -az --delete -e "ssh $SSH_OPTS" \
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
        "$LOCAL_DIR/" "$RT:$REMOTE_DIR/"

    echo "📤 [2/4] 同步輸入檔案到遠端 $INPUT_DIR..."
    ssh $SSH_OPTS "$RT" "mkdir -p $REMOTE_DIR/$INPUT_DIR $REMOTE_DIR/$OUTPUT_DIR"
    rsync -az --delete -e "ssh $SSH_OPTS" "$LOCAL_DIR/$INPUT_DIR/" "$RT:$REMOTE_DIR/$INPUT_DIR/"

    echo "🧹 [2.5/4] 清理 DGX 上先前殘留的 stale 轉換容器與哨兵檔..."
    # 同步清除舊哨兵檔 (獨立一步)：避免與後續輪詢競爭，防止讀到上一輪殘留的 .done。
    ssh $SSH_OPTS "$RT" "
        docker ps -a --filter '$CONTAINER_FILTER' -q | xargs -r docker rm -f
        cd $REMOTE_DIR && rm -f $DONE_REL $LOG_REL $START_REL
    "

    echo "⚙️ [3/4] 在 DGX 上以 detach 模式啟動轉換 (連線中斷不會中止遠端作業)..."
    # setsid + nohup：與本 SSH 連線解耦，斷線後容器仍會跑完。
    # 容器內以 root 執行，worker 的 trap 會在結束/中斷時 chown 回遠端使用者。
    # 只把 setsid 這一項背景化 ({ …& })，cd/date 仍在前景執行。
    # 若把整條 && 鏈一起背景化，subshell 會等 worker 跑完而一直握著 ssh channel，導致 ssh 不返回。
    ssh $SSH_OPTS "$RT" \
        "cd $REMOTE_DIR && date +%s > $START_REL && \
         { setsid nohup bash remote_worker.sh '$INPUT_DIR' '$OUTPUT_DIR' '$WORKERS' '$FORCE_FLAG' '$RAW_FLAG' '$DONE_REL' \
           > $LOG_REL 2>&1 < /dev/null & } && echo '🛰️  已在遠端背景啟動轉換'"

    echo "⏳ [4/4] 監看遠端進度 (每 ${POLL_INTERVAL}s 更新)。"
    echo "   💡 這裡可安全 Ctrl-C 離開，遠端會繼續跑；之後用 ./remote_run.sh status 接回監看。"
    monitor_and_harvest run
}

case "$CMD" in
    run)    do_run ;;
    status) do_status ;;
    stop)   do_stop ;;
    *)
        echo "用法: ./remote_run.sh [run|status|stop]"
        echo "  run    (預設) 啟動新轉換並監看"
        echo "  status 監看目前這輪的進度/ETA，跑完自動收割"
        echo "  stop   停掉遠端容器並清除哨兵檔"
        exit 1
        ;;
esac
