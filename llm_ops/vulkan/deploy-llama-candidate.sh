#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-status}"
CANDIDATE="${2:-}"
SECONDARY="${SECONDARY:-root@10.30.0.2}"
PRIMARY_SERVICE="${PRIMARY_SERVICE:-llm-gemma4-primary.service}"
SECONDARY_SERVICE="${SECONDARY_SERVICE:-llm-gpu2-rpc-worker.service}"
PRIMARY_CANDIDATES="${PRIMARY_CANDIDATES:-/mnt/ssd/llm-distributed/candidates}"
SECONDARY_CANDIDATES="${SECONDARY_CANDIDATES:-/opt/llm-rpc/candidates}"
PRIMARY_DROPIN="/etc/systemd/system/${PRIMARY_SERVICE}.d/30-llama-candidate.conf"
SECONDARY_DROPIN="/etc/systemd/system/${SECONDARY_SERVICE}.d/30-llama-candidate.conf"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
SLOTS_URL="${SLOTS_URL:-http://127.0.0.1:8080/slots}"
IDLE_WINDOW_SECONDS="${IDLE_WINDOW_SECONDS:-20}"
IDLE_TIMEOUT_SECONDS="${IDLE_TIMEOUT_SECONDS:-900}"
NO_TRANSPOSE_A="${GGML_VK_NO_TRANSPOSE_A:-}"

exec 9>/run/lock/gemma-vulkan-deploy.lock
flock -n 9 || { echo "another Vulkan deployment is already running" >&2; exit 1; }

wait_for_health() {
    local deadline=$((SECONDS + 900))
    until curl --fail --silent --max-time 5 "$HEALTH_URL" | grep -q '"status":"ok"'; do
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

tree_digest_command() {
    local root=$1
    printf "cd %q && find . -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum" "$root"
}

validate_candidate() {
    [[ "$CANDIDATE" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
        echo "invalid candidate name: $CANDIDATE" >&2
        return 1
    }
    [[ -z "$NO_TRANSPOSE_A" || "$NO_TRANSPOSE_A" == 1 ]] || {
        echo "GGML_VK_NO_TRANSPOSE_A must be empty or 1" >&2
        return 1
    }

    PRIMARY_ROOT="${PRIMARY_CANDIDATE_ROOT:-${PRIMARY_CANDIDATES}/llama-${CANDIDATE}}"
    SECONDARY_ROOT="${SECONDARY_CANDIDATE_ROOT:-${SECONDARY_CANDIDATES}/llama-${CANDIDATE}}"
    if [[ ! -d "$PRIMARY_ROOT" && -d "${PRIMARY_CANDIDATES}/llama-b10012-${CANDIDATE}" ]]; then
        PRIMARY_ROOT="${PRIMARY_CANDIDATES}/llama-b10012-${CANDIDATE}"
    fi
    if ! ssh -n -o BatchMode=yes "$SECONDARY" "test -d '$SECONDARY_ROOT'" &&
       ssh -n -o BatchMode=yes "$SECONDARY" "test -d '${SECONDARY_CANDIDATES}/llama-b10012-${CANDIDATE}'"; then
        SECONDARY_ROOT="${SECONDARY_CANDIDATES}/llama-b10012-${CANDIDATE}"
    fi
    local primary_manifest="${PRIMARY_ROOT}/gemma-vulkan-build.txt"
    local secondary_manifest="${SECONDARY_ROOT}/gemma-vulkan-build.txt"
    [[ -x "${PRIMARY_ROOT}/llama-server" && -x "${PRIMARY_ROOT}/ggml-rpc-server" ]]
    grep -Fxq "candidate=${CANDIDATE}" "$primary_manifest"
    ssh -n -o BatchMode=yes "$SECONDARY" \
        "test -x '$SECONDARY_ROOT/llama-server' && test -x '$SECONDARY_ROOT/ggml-rpc-server' && grep -Fxq 'candidate=$CANDIDATE' '$secondary_manifest'"

    local primary_digest secondary_digest
    primary_digest=$(bash -c "$(tree_digest_command "$PRIMARY_ROOT")" | awk '{print $1}')
    secondary_digest=$(ssh -n -o BatchMode=yes "$SECONDARY" \
        "$(tree_digest_command "$SECONDARY_ROOT")" | awk '{print $1}')
    [[ "$primary_digest" == "$secondary_digest" ]] || {
        echo "candidate trees differ: primary=$primary_digest secondary=$secondary_digest" >&2
        return 1
    }
    echo "verified candidate tree: ${CANDIDATE} ${primary_digest}"
}

write_dropins() (
    local primary_tmp secondary_tmp
    primary_tmp=$(mktemp)
    secondary_tmp=$(mktemp)
    trap 'rm -f "$primary_tmp" "$secondary_tmp"' EXIT
    {
        echo '[Service]'
        echo "Environment=RUNTIME_ROOT=${PRIMARY_ROOT}"
        [[ -z "$NO_TRANSPOSE_A" ]] || echo "Environment=GGML_VK_NO_TRANSPOSE_A=${NO_TRANSPOSE_A}"
    } >"$primary_tmp"
    {
        echo '[Service]'
        echo "Environment=RUNTIME_ROOT=${SECONDARY_ROOT}"
        [[ -z "$NO_TRANSPOSE_A" ]] || echo "Environment=GGML_VK_NO_TRANSPOSE_A=${NO_TRANSPOSE_A}"
    } >"$secondary_tmp"

    install -d -m 0755 "$(dirname "$PRIMARY_DROPIN")"
    install -m 0644 "$primary_tmp" "$PRIMARY_DROPIN"
    ssh -n -o BatchMode=yes "$SECONDARY" "install -d -m 0755 '$(dirname "$SECONDARY_DROPIN")'"
    ssh -o BatchMode=yes "$SECONDARY" "cat >'$SECONDARY_DROPIN'" <"$secondary_tmp"
    ssh -n -o BatchMode=yes "$SECONDARY" "chmod 0644 '$SECONDARY_DROPIN'"
)

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

verify_running_candidate() {
    local primary_pid secondary_pid primary_exe secondary_exe
    primary_pid=$(systemctl show "$PRIMARY_SERVICE" -p MainPID --value)
    secondary_pid=$(ssh -n -o BatchMode=yes "$SECONDARY" \
        systemctl show "$SECONDARY_SERVICE" -p MainPID --value)
    primary_exe=$(readlink -f "/proc/${primary_pid}/exe")
    secondary_exe=$(ssh -n -o BatchMode=yes "$SECONDARY" \
        "readlink -f '/proc/${secondary_pid}/exe'")
    [[ "$primary_exe" == "${PRIMARY_ROOT}/llama-server" ]]
    [[ "$secondary_exe" == "${SECONDARY_ROOT}/ggml-rpc-server" ]]
    echo "running primary:   $primary_exe"
    echo "running secondary: $secondary_exe"
}

case "$MODE" in
    enable)
        validate_candidate
        wait_for_idle_window
        write_dropins
        if ! restart_stack || ! verify_running_candidate; then
            echo "candidate failed; rolling back runtime drop-ins" >&2
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
        systemctl show "$PRIMARY_SERVICE" -p MainPID -p Environment --no-pager
        ssh -n -o BatchMode=yes "$SECONDARY" \
            systemctl show "$SECONDARY_SERVICE" -p MainPID -p Environment --no-pager
        ;;
    *)
        echo "usage: $0 {enable CANDIDATE|rollback|status}" >&2
        exit 2
        ;;
esac
