# llama.cpp b10076 GFX1200 candidates

All patches apply independently to official llama.cpp tag `b10076`, commit
`305ba519ab61cdff8044922cba2347826a04453f`.  They are clean-room Vulkan
experiments: CUDA/FlashAttention work supplied algorithmic hypotheses only;
no CUDA source was copied.  Every candidate was compiled to GLSL/SPIR-V on
both GFX1200 hosts and benchmarked against the unchanged b10076 tree with the
same model, Mesa/RADV 25.3.6, AMD `COMPUTE` profile and forced token path.

The production acceptance gate is at least `+5%` median prefill, no more than
`-2%` median decode, exact output, Vulkan reference tests and production E2E.
None of the patches below passed the complete gate, so production stays on the
clean b10076 binary.  The patches remain here as reproducible negative and
research results.

| Patch | Native Vulkan idea | Prefill | Decode | Wall | Decision |
|---|---|---:|---:|---:|---|
| `0001` | RDNA4 Q4_K row mapping `rm_kq=1` | -0.063% | +0.082% | -0.101% | reject: noise |
| `0002` | reuse one Q4_K activation tile across output rows | +0.271% | -0.001% | -0.170% | reject: below gate |
| `0003` | integer Q4_K row mapping `rm_kq=2` | +0.525% | +0.015% | -0.216% | reject: below gate |
| `0004` | 32-value Q4_K MMVQ value tile | +0.332% | +0.197% | -0.168% | reject: backend-reference mismatch |
| `0005` | subgroup XOR scale broadcast | +0.174% | -0.332% | +0.160% | reject |
| `0006` | subgroup quad scale sharing | +0.103% | -0.624% | +0.133% | reject |
| `0007` | local head_dim=256 LDS K/V staging | -1.673% | -0.327% | +1.142% | reject |
| `0008` | independent scalar dispatch for global head_dim=512 | -3.152% | +0.513% | +1.389% | reject |
| `0009` | global head_dim=512 `Bc=128`, eight wave64 subgroups | +0.460% | -0.380% | -0.103% | reject: below gate |
| `0010` | global head_dim=512 persistent `Br=32`, reuse K/V for two Q tiles | **+2.557%** | +0.056% | **-1.253%** | research-only: best patch, below gate |

The `0009` and `0010` global-attention implementations each passed all
`112/112` targeted `FLASH_ATTN_EXT(hsk=512,hsv=512)` CPU-reference tests on
both GPUs and retained all three forced output hashes.  `0010` contains the
strongest FA4-inspired result: per-layer dispatch, tiled online softmax,
KHR cooperative matrices, persistent workgroups, and fused QK → softmax → V.
Its improvement is real but too small to justify replacing the clean runtime.

GFX1200 exposes 64 KiB LDS.  A double buffer for a single F16 global K tile is
already `2 * 64 * 512 * 2 = 128 KiB`, before V, Q, probability, reduction or
output state.  It cannot be resident.  The feasible local single-buffer
staging path (`0007`) also regressed, so an LDS double-buffer variant was
rejected at the resource-feasibility gate rather than shipped as an invalid or
occupancy-destroying kernel.  Upstream dynamic split-K remains enabled; the
profile showed enough global-attention workgroups, so forcing split-K would
add reduction traffic rather than solve an occupancy shortage.

Apply one candidate to a clean worktree:

```bash
git -C llama.cpp checkout b10076
git -C llama.cpp reset --hard b10076
git -C llama.cpp apply ../patches/llama.cpp-b10076/0010-vulkan-gfx1200-global-fa-br32.patch
```

Raw request evidence is indexed in
[`../../docs/results/README.md`](../../docs/results/README.md).  Build,
deployment, idle-window enforcement and rollback commands are documented in
[`../../docs/vulkan-rdna4-performance.md`](../../docs/vulkan-rdna4-performance.md).
