#!/usr/bin/env bash
set -euo pipefail

MESA_VERSION="${MESA_VERSION:-25.3.6}"
MESA_SHA256="${MESA_SHA256:-59217efeac3b64e7ced958324b9db7494f1e0741aeb22d780276514cc1b8f206}"
WORK_ROOT="${WORK_ROOT:-/mnt/ssd/llm-distributed/candidates/mesa-${MESA_VERSION}-build}"
PREFIX="${PREFIX:-/mnt/ssd/llm-distributed/candidates/mesa-${MESA_VERSION}-radv}"
JOBS="${JOBS:-$(nproc)}"
ARCHIVE="${WORK_ROOT}/mesa-${MESA_VERSION}.tar.xz"
SOURCE="${WORK_ROOT}/mesa-${MESA_VERSION}"
BUILD="${WORK_ROOT}/build"
MANIFEST="${PREFIX}/gemma-radv-build.txt"

for command in curl meson ninja sha256sum tar; do
    command -v "$command" >/dev/null || {
        echo "missing build command: $command" >&2
        exit 1
    }
done

if [[ -f "$MANIFEST" ]]; then
    grep -qx "mesa_version=${MESA_VERSION}" "$MANIFEST"
    grep -qx "source_sha256=${MESA_SHA256}" "$MANIFEST"
    echo "verified existing Mesa/RADV candidate: $PREFIX"
    exit 0
fi
if [[ -e "$PREFIX" ]]; then
    echo "refusing to overwrite unverified prefix: $PREFIX" >&2
    exit 1
fi

install -d -m 0755 "$WORK_ROOT"
if [[ -f "$ARCHIVE" ]] && ! printf '%s  %s\n' "$MESA_SHA256" "$ARCHIVE" | sha256sum --check --strict -; then
    curl --fail --location --retry 3 --continue-at - \
        --output "$ARCHIVE" \
        "https://archive.mesa3d.org/mesa-${MESA_VERSION}.tar.xz"
fi
if [[ ! -f "$ARCHIVE" ]]; then
    curl --fail --location --retry 3 \
        --output "$ARCHIVE" \
        "https://archive.mesa3d.org/mesa-${MESA_VERSION}.tar.xz"
fi
printf '%s  %s\n' "$MESA_SHA256" "$ARCHIVE" | sha256sum --check --strict -

if [[ ! -f "$SOURCE/meson.build" ]]; then
    tar -xf "$ARCHIVE" -C "$WORK_ROOT"
fi

if [[ ! -f "$BUILD/build.ninja" ]]; then
    meson setup "$BUILD" "$SOURCE" \
        --prefix "$PREFIX" \
        --buildtype release \
        --strip \
        -Dplatforms=[] \
        -Dgallium-drivers=[] \
        -Dvulkan-drivers=amd \
        -Dvulkan-layers=[] \
        -Dopengl=false \
        -Dgles1=disabled \
        -Dgles2=disabled \
        -Dgbm=disabled \
        -Dglx=disabled \
        -Degl=disabled \
        -Dllvm=disabled \
        -Dshared-llvm=disabled \
        -Dvalgrind=disabled \
        -Dlibunwind=disabled \
        -Dlmsensors=disabled \
        -Dbuild-tests=false \
        -Dbuild-radv-tests=false \
        -Dtools=[] \
        -Dvideo-codecs=[]
fi

ninja -C "$BUILD" -j "$JOBS"
meson install -C "$BUILD"

icd="$(find "$PREFIX" -type f -path '*/vulkan/icd.d/*radeon*.json' -print -quit)"
driver="$(find "$PREFIX" -type f -name 'libvulkan_radeon.so' -print -quit)"
[[ -n "$icd" && -n "$driver" ]] || {
    echo "Mesa install is missing the RADV ICD or driver" >&2
    exit 1
}

{
    echo "mesa_version=${MESA_VERSION}"
    echo "source_sha256=${MESA_SHA256}"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "compiler=$(cc --version | head -n 1)"
    echo "kernel=$(uname -r)"
    echo "icd=${icd}"
    echo "driver=${driver}"
    sha256sum "$icd" "$driver"
} >"$MANIFEST"
chmod -R a+rX "$PREFIX"
echo "Mesa/RADV candidate installed at $PREFIX"
