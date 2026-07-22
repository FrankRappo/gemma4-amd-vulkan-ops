#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-status}"
SECONDARY="${SECONDARY:-root@10.30.0.2}"
PRIMARY_SERVICE="${PRIMARY_SERVICE:-llm-gemma4-primary.service}"
SECONDARY_SERVICE="${SECONDARY_SERVICE:-llm-gpu2-rpc-worker.service}"
PRIMARY_ICD="${PRIMARY_ICD:-/mnt/ssd/llm-distributed/candidates/mesa-25.3.6-radv/share/vulkan/icd.d/radeon_icd.x86_64.json}"
SECONDARY_ICD="${SECONDARY_ICD:-/opt/llm-rpc/candidates/mesa-25.3.6-radv/share/vulkan/icd.d/radeon_icd.x86_64.json}"
PRIMARY_DROPIN="/etc/systemd/system/${PRIMARY_SERVICE}.d/20-mesa-radv.conf"
SECONDARY_DROPIN="/etc/systemd/system/${SECONDARY_SERVICE}.d/20-mesa-radv.conf"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
SLOTS_URL="${SLOTS_URL:-http://127.0.0.1:8080/slots}"
IDLE_WINDOW_SECONDS="${IDLE_WINDOW_SECONDS:-20}"
IDLE_TIMEOUT_SECONDS="${IDLE_TIMEOUT_SECONDS:-900}"

exec 9>/run/lock/gemma-vulkan-deploy.lock
flock -n 9 || { echo "another Vulkan deployment is already running" >&2; exit 1; }

wait_for_health() {
    local deadline=$((SECONDS + 900))
    until curl --fail --silent "$HEALTH_URL" | grep -q '"status":"ok"'; do
        if ((SECONDS >= deadline)); then
            return 1
        fi
        sleep 2
    done
}

slots_are_idle() {
    curl --fail --silent --max-time 5 "$SLOTS_URL" | python3 -c '
import json, sys
slots = json.load(sys.stdin)
raise SystemExit(any(slot.get("is_processing", False) for slot in slots))
'
}

wait_for_idle_window() {
    local deadline=$((SECONDS + IDLE_TIMEOUT_SECONDS))
    local idle_since=0
    while ((SECONDS < deadline)); do
        if slots_are_idle; then
            if ((idle_since == 0)); then
                idle_since=$SECONDS
            elif ((SECONDS - idle_since >= IDLE_WINDOW_SECONDS)); then
                # Close the one-second polling race as much as possible before
                # touching systemd.  If a request arrived, restart the window.
                slots_are_idle && return 0
                idle_since=0
            fi
        else
            idle_since=0
        fi
        sleep 1
    done
    echo "production did not remain idle for ${IDLE_WINDOW_SECONDS}s" >&2
    return 1
}

write_dropins() {
    [[ -r "$PRIMARY_ICD" ]] || { echo "missing primary ICD: $PRIMARY_ICD" >&2; return 1; }
    ssh -n -o BatchMode=yes "$SECONDARY" "test -r '$SECONDARY_ICD'"
    install -d -m 0755 "$(dirname "$PRIMARY_DROPIN")"
    cat >"$PRIMARY_DROPIN" <<EOF
[Service]
Environment=VK_DRIVER_FILES=$PRIMARY_ICD
Environment=VK_ICD_FILENAMES=$PRIMARY_ICD
EOF
    ssh -n -o BatchMode=yes "$SECONDARY" "install -d -m 0755 '$(dirname "$SECONDARY_DROPIN")'; cat >'$SECONDARY_DROPIN' <<'EOF'
[Service]
Environment=VK_DRIVER_FILES=$SECONDARY_ICD
Environment=VK_ICD_FILENAMES=$SECONDARY_ICD
EOF"
}

disable_dropins() {
    local suffix="disabled-$(date -u +%Y%m%dT%H%M%SZ)"
    if [[ -e "$PRIMARY_DROPIN" ]]; then
        mv "$PRIMARY_DROPIN" "${PRIMARY_DROPIN}.${suffix}"
    fi
    ssh -n -o BatchMode=yes "$SECONDARY" \
        "if test -e '$SECONDARY_DROPIN'; then mv '$SECONDARY_DROPIN' '${SECONDARY_DROPIN}.${suffix}'; fi"
}

restart_stack() {
    systemctl daemon-reload
    ssh -n -o BatchMode=yes "$SECONDARY" systemctl daemon-reload
    systemctl stop "$PRIMARY_SERVICE"
    ssh -n -o BatchMode=yes "$SECONDARY" systemctl restart "$SECONDARY_SERVICE"
    systemctl start "$PRIMARY_SERVICE"
    wait_for_health
}

case "$MODE" in
    enable)
        wait_for_idle_window
        write_dropins
        if ! restart_stack; then
            echo "candidate failed; rolling back systemd environment" >&2
            disable_dropins
            restart_stack
            exit 1
        fi
        ;;
    rollback)
        wait_for_idle_window
        disable_dropins
        restart_stack
        ;;
    status)
        systemctl is-active "$PRIMARY_SERVICE"
        ssh -n -o BatchMode=yes "$SECONDARY" systemctl is-active "$SECONDARY_SERVICE"
        systemctl show "$PRIMARY_SERVICE" -p Environment --no-pager
        ssh -n -o BatchMode=yes "$SECONDARY" \
            systemctl show "$SECONDARY_SERVICE" -p Environment --no-pager
        ;;
    *)
        echo "usage: $0 {enable|rollback|status}" >&2
        exit 2
        ;;
esac
