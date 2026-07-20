#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/mnt/ssd/llm-distributed}
RUNTIME_ROOT=${RUNTIME_ROOT:-$BASE/runtime/llama.cpp-b10012-vulkan-x64/llama-b10012}
MODEL=${MODEL:-$BASE/models/gemma-4-31b-abliterated-Q4_K_M.gguf}
MMPROJ=${MMPROJ:-$BASE/models/vision/mmproj-gemma-4-31B-it-Q8_0.gguf}
DRAFT_MODEL=${DRAFT_MODEL:-$BASE/models/draft/gemma-4-31B-it-assistant-Q8_0.gguf}
RPC_ADDR=${RPC_ADDR:-10.30.0.2:50053}
RPC_WAIT_SECONDS=${RPC_WAIT_SECONDS:-180}
CTX_SIZE=${CTX_SIZE:-32768}
PARALLEL=${PARALLEL:-1}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8080}
ENABLE_MTP=${ENABLE_MTP:-0}
MTP_N_MAX=${MTP_N_MAX:-1}
VISION_MIN_TOKENS=${VISION_MIN_TOKENS:-280}
VISION_MAX_TOKENS=${VISION_MAX_TOKENS:-1120}
VISION_BATCH_SIZE=${VISION_BATCH_SIZE:-1280}
VISION_UBATCH_SIZE=${VISION_UBATCH_SIZE:-1280}
VISION_MTMD_BATCH_MAX_TOKENS=${VISION_MTMD_BATCH_MAX_TOKENS:-1280}

for value_name in \
  VISION_MIN_TOKENS \
  VISION_MAX_TOKENS \
  VISION_BATCH_SIZE \
  VISION_UBATCH_SIZE \
  VISION_MTMD_BATCH_MAX_TOKENS; do
  value=${!value_name}
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    echo "$value_name must be a positive integer, got: $value" >&2
    exit 2
  fi
done

case "$VISION_MIN_TOKENS" in
  70|140|280|560|1120) ;;
  *) echo "unsupported VISION_MIN_TOKENS=$VISION_MIN_TOKENS" >&2; exit 2 ;;
esac
case "$VISION_MAX_TOKENS" in
  70|140|280|560|1120) ;;
  *) echo "unsupported VISION_MAX_TOKENS=$VISION_MAX_TOKENS" >&2; exit 2 ;;
esac
if (( VISION_MIN_TOKENS > VISION_MAX_TOKENS )); then
  echo "VISION_MIN_TOKENS must not exceed VISION_MAX_TOKENS" >&2
  exit 2
fi
for value_name in \
  VISION_BATCH_SIZE \
  VISION_UBATCH_SIZE \
  VISION_MTMD_BATCH_MAX_TOKENS; do
  if (( ${!value_name} < VISION_MAX_TOKENS )); then
    echo "$value_name must be >= VISION_MAX_TOKENS ($VISION_MAX_TOKENS)" >&2
    exit 2
  fi
done

SERVER=$RUNTIME_ROOT/llama-server
for required in "$SERVER" "$MODEL" "$MMPROJ"; do
  if [[ ! -r "$required" ]]; then
    echo "required file is not readable: $required" >&2
    exit 1
  fi
done

rpc_host=${RPC_ADDR%:*}
rpc_port=${RPC_ADDR##*:}
deadline=$((SECONDS + RPC_WAIT_SECONDS))
until timeout 1 bash -c "</dev/tcp/$rpc_host/$rpc_port" 2>/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "RPC worker $RPC_ADDR did not become ready in ${RPC_WAIT_SECONDS}s" >&2
    exit 1
  fi
  sleep 2
done

export LD_LIBRARY_PATH="$RUNTIME_ROOT${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

args=(
  --model "$MODEL"
  --mmproj "$MMPROJ"
  --mmproj-offload
  --rpc "$RPC_ADDR"
  --device Vulkan0,RPC0
  --split-mode layer
  --tensor-split 1,1
  --gpu-layers auto
  --ctx-size "$CTX_SIZE"
  --parallel "$PARALLEL"
  --batch-size "$VISION_BATCH_SIZE"
  # Gemma 4 vision uses non-causal image attention. The micro-batch must hold
  # the full image-token chunk or llama.cpp aborts before text decoding.
  --ubatch-size "$VISION_UBATCH_SIZE"
  --image-min-tokens "$VISION_MIN_TOKENS"
  --image-max-tokens "$VISION_MAX_TOKENS"
  --mtmd-batch-max-tokens "$VISION_MTMD_BATCH_MAX_TOKENS"
  --cache-type-k q4_0
  --cache-type-v q4_0
  --cache-ram 0
  --fit off
  --reasoning on
  --reasoning-budget -1
  --jinja
  --host "$HOST"
  --port "$PORT"
)

if [[ "$ENABLE_MTP" == 1 ]]; then
  if [[ ! -r "$DRAFT_MODEL" ]]; then
    echo "MTP draft model is not readable: $DRAFT_MODEL" >&2
    exit 1
  fi
  args+=(
    --spec-type draft-mtp
    --spec-draft-model "$DRAFT_MODEL"
    --spec-draft-device Vulkan0
    --spec-draft-ngl all
    --spec-draft-n-max "$MTP_N_MAX"
  )
fi

exec "$SERVER" "${args[@]}"
