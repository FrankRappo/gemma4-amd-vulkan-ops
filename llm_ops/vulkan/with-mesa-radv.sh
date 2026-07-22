#!/usr/bin/env bash
set -euo pipefail

PREFIX="${MESA_RADV_PREFIX:-/mnt/ssd/llm-distributed/candidates/mesa-25.3.6-radv}"
icd="$(find "$PREFIX" -type f -path '*/vulkan/icd.d/*radeon*.json' -print -quit)"
libdir="$(dirname "$(find "$PREFIX" -type f -name 'libvulkan_radeon.so' -print -quit)")"

if [[ -z "$icd" || -z "$libdir" ]]; then
    echo "invalid Mesa/RADV prefix: $PREFIX" >&2
    exit 1
fi

# VK_DRIVER_FILES is the current Vulkan-loader override. VK_ICD_FILENAMES is
# retained for the Debian 13 loader and older diagnostic tools.
export VK_DRIVER_FILES="$icd"
export VK_ICD_FILENAMES="$icd"
export LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$@"
