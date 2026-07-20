#!/usr/bin/env bash
set -euo pipefail

RUNTIME_ROOT=${RUNTIME_ROOT:-/opt/llm-rpc/runtime/llama.cpp-b10012/llama-b10012}
HOST=${HOST:-10.30.0.2}
PORT=${PORT:-50053}
RPC_SERVER=$RUNTIME_ROOT/ggml-rpc-server

if [[ ! -x "$RPC_SERVER" ]]; then
  echo "RPC server is not executable: $RPC_SERVER" >&2
  exit 1
fi

export LD_LIBRARY_PATH="$RUNTIME_ROOT${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$RPC_SERVER" --host "$HOST" --port "$PORT" --device Vulkan0
