#!/usr/bin/env bash
set -euo pipefail

BASE_COMMIT="${BASE_COMMIT:-c71854292f7c367cc3b35939f88121d81945472f}"
SOURCE_REPO="${SOURCE_REPO:-/mnt/ssd/llm-distributed/src/llama.cpp}"
CANDIDATE="${CANDIDATE:-rm-kq1}"
WORKTREE="${WORKTREE:-/mnt/ssd/llm-distributed/candidates/src/llama-b10012-${CANDIDATE}}"
BUILD="${BUILD:-/mnt/ssd/llm-distributed/candidates/build/llama-b10012-${CANDIDATE}}"
PREFIX="${PREFIX:-/mnt/ssd/llm-distributed/candidates/llama-b10012-${CANDIDATE}}"
case "$CANDIDATE" in
    rm-kq1)
        DEFAULT_PATCH="$(dirname "$0")/../../patches/llama.cpp-b10012/0001-vulkan-rdna4-rm-kq-1.patch"
        ;;
    kquant-transpose)
        DEFAULT_PATCH="$(dirname "$0")/../../patches/llama.cpp-b10012/0002-vulkan-kquant-transposed-a-cm1.patch"
        ;;
    *)
        DEFAULT_PATCH=""
        ;;
esac
PATCH_FILE="${PATCH_FILE:-$DEFAULT_PATCH}"
JOBS="${JOBS:-$(nproc)}"
MANIFEST="$PREFIX/gemma-vulkan-build.txt"

for command in cmake git sha256sum; do
    command -v "$command" >/dev/null || {
        echo "missing build command: $command" >&2
        exit 1
    }
done
[[ -n "$PATCH_FILE" && -r "$PATCH_FILE" ]] || {
    echo "missing patch for candidate '$CANDIDATE': $PATCH_FILE" >&2
    exit 1
}
git -C "$SOURCE_REPO" cat-file -e "${BASE_COMMIT}^{commit}"

patch_sha256="$(sha256sum "$PATCH_FILE" | awk '{print $1}')"
if [[ -f "$MANIFEST" ]]; then
    grep -qx "base_commit=${BASE_COMMIT}" "$MANIFEST"
    grep -qx "patch_sha256=${patch_sha256}" "$MANIFEST"
    echo "verified existing llama.cpp candidate: $PREFIX"
    exit 0
fi
if [[ -e "$PREFIX" ]]; then
    echo "refusing to overwrite unverified prefix: $PREFIX" >&2
    exit 1
fi

install -d -m 0755 "$(dirname "$WORKTREE")" "$(dirname "$BUILD")"
if [[ ! -e "$WORKTREE/.git" ]]; then
    git -C "$SOURCE_REPO" worktree add --detach "$WORKTREE" "$BASE_COMMIT"
fi
[[ "$(git -C "$WORKTREE" rev-parse HEAD)" == "$BASE_COMMIT" ]]
if git -C "$WORKTREE" apply --check "$PATCH_FILE"; then
    git -C "$WORKTREE" apply "$PATCH_FILE"
elif ! git -C "$WORKTREE" diff --quiet -- ggml/src/ggml-vulkan/ggml-vulkan.cpp; then
    echo "using an already patched candidate worktree"
else
    echo "patch does not apply cleanly" >&2
    exit 1
fi

if [[ ! -f "$BUILD/CMakeCache.txt" ]]; then
    cmake -S "$WORKTREE" -B "$BUILD" \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=ON \
        -DGGML_NATIVE=OFF \
        -DGGML_AVX=ON \
        -DGGML_AVX2=ON \
        -DGGML_F16C=ON \
        -DGGML_FMA=ON \
        -DGGML_BMI2=ON \
        -DGGML_AVX512=OFF \
        -DGGML_VULKAN=ON \
        -DGGML_RPC=ON \
        -DGGML_RPC_RDMA=OFF \
        -DLLAMA_BUILD_SERVER=ON \
        -DLLAMA_BUILD_TESTS=ON \
        -DLLAMA_BUILD_TOOLS=ON
fi

cmake --build "$BUILD" --parallel "$JOBS" --target \
    llama-server llama-bench ggml-rpc-server test-backend-ops
install -d -m 0755 "$PREFIX"
cp -a "$BUILD/bin/." "$PREFIX/"
{
    echo "base_commit=${BASE_COMMIT}"
    echo "candidate=${CANDIDATE}"
    echo "patch_sha256=${patch_sha256}"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "compiler=$(c++ --version | head -n 1)"
    "$PREFIX/llama-server" --version 2>&1 | sed 's/^/version: /'
    find "$PREFIX" -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum
} >"$MANIFEST"
chmod -R a+rX "$PREFIX"
echo "llama.cpp candidate installed at $PREFIX"
