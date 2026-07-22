#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "run as root" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update --allow-releaseinfo-change
apt-get install --no-install-recommends -y \
    bison \
    build-essential \
    flex \
    libdrm-dev \
    libelf-dev \
    libexpat1-dev \
    libvulkan-dev \
    meson \
    ninja-build \
    pkg-config \
    python3-mako \
    python3-packaging \
    python3-ply \
    python3-yaml \
    python3-zstandard \
    zlib1g-dev
