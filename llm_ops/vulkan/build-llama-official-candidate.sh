#!/usr/bin/env bash
set -euo pipefail

TAG="${TAG:-b10076}"
SOURCE_REPO="${SOURCE_REPO:-/mnt/ssd/llm-distributed/src/llama.cpp}"
CANDIDATE="${CANDIDATE:-$TAG}"
PATCH_FILE="${PATCH_FILE:-}"
WORKTREE="${WORKTREE:-/mnt/ssd/llm-distributed/candidates/src/llama-${CANDIDATE}}"
BUILD="${BUILD:-/mnt/ssd/llm-distributed/candidates/build/llama-${CANDIDATE}}"
PREFIX="${PREFIX:-/mnt/ssd/llm-distributed/candidates/llama-${CANDIDATE}}"
JOBS="${JOBS:-$(nproc)}"
MANIFEST="$PREFIX/gemma-vulkan-build.txt"

[[ "$TAG" =~ ^b[0-9]+$ ]] || { echo "invalid llama.cpp tag: $TAG" >&2; exit 2; }
[[ "$CANDIDATE" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
    echo "invalid candidate name: $CANDIDATE" >&2
    exit 2
}
for command in cmake git sha256sum; do
    command -v "$command" >/dev/null || {
        echo "missing build command: $command" >&2
        exit 1
    }
done

git -C "$SOURCE_REPO" fetch --force origin "refs/tags/${TAG}:refs/tags/${TAG}"
commit=$(git -C "$SOURCE_REPO" rev-list -n 1 "$TAG")
git -C "$SOURCE_REPO" merge-base --is-ancestor "$commit" "$TAG"
patch_sha256=none
if [[ -n "$PATCH_FILE" ]]; then
    [[ -r "$PATCH_FILE" ]] || { echo "patch is not readable: $PATCH_FILE" >&2; exit 1; }
    patch_sha256=$(sha256sum "$PATCH_FILE" | awk '{print $1}')
fi

if [[ -f "$MANIFEST" ]]; then
    grep -Fxq "tag=${TAG}" "$MANIFEST"
    grep -Fxq "commit=${commit}" "$MANIFEST"
    grep -Fxq "candidate=${CANDIDATE}" "$MANIFEST"
    grep -Fxq "patch_sha256=${patch_sha256}" "$MANIFEST"
    echo "verified existing official llama.cpp candidate: $PREFIX"
    exit 0
fi
if [[ -e "$PREFIX" ]]; then
    echo "refusing to overwrite unverified prefix: $PREFIX" >&2
    exit 1
fi

install -d -m 0755 "$(dirname "$WORKTREE")" "$(dirname "$BUILD")"
if [[ ! -e "$WORKTREE/.git" ]]; then
    git -C "$SOURCE_REPO" worktree add --detach "$WORKTREE" "$commit"
fi
[[ "$(git -C "$WORKTREE" rev-parse HEAD)" == "$commit" ]]
if [[ -n "$PATCH_FILE" ]]; then
    if git -C "$WORKTREE" apply --check "$PATCH_FILE"; then
        git -C "$WORKTREE" apply "$PATCH_FILE"
    elif git -C "$WORKTREE" diff --quiet; then
        echo "patch does not apply cleanly" >&2
        exit 1
    fi
else
    git -C "$WORKTREE" diff --quiet
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
    echo "tag=${TAG}"
    echo "commit=${commit}"
    echo "candidate=${CANDIDATE}"
    echo "patch_sha256=${patch_sha256}"
    if [[ "$patch_sha256" == none ]]; then
        echo "source=official-llama.cpp-tag"
    else
        echo "source=official-llama.cpp-tag-plus-patch"
    fi
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "compiler=$(c++ --version | head -n 1)"
    "$PREFIX/llama-server" --version 2>&1 | sed 's/^/version: /'
    find "$PREFIX" -maxdepth 1 -type f ! -name gemma-vulkan-build.txt \
        -print0 | sort -z | xargs -0 sha256sum
} >"$MANIFEST"
chmod -R a+rX "$PREFIX"
echo "official llama.cpp candidate installed at $PREFIX"
