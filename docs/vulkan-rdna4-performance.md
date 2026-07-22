# GFX1200 Vulkan performance work

## Objective and non-regression gates

Maximize Gemma 4 31B throughput across the two GFX1200 GPUs without changing
model weights, text output, Vision behavior, RPC correctness, two-slot
capacity, or service stability. A candidate is deployable only when all of the
following hold:

1. deterministic output hashes match its control;
2. median prefill improves by at least 5%;
3. median generation does not regress by more than 2%;
4. Vulkan backend Q4_K operations pass against the CPU reference;
5. text, Vision and two-host RPC production smoke tests pass;
6. no OOM, device loss, service restart loop, or material VRAM-reserve loss;
7. rollback to the preserved b10012 runtime and system Mesa succeeds.

The benchmark requires a continuous idle interval before every sample. A busy
or unresponsive `/slots` endpoint resets that interval, so production traffic
cannot silently contaminate an artifact.

## Immutable baseline and backup

- llama.cpp base: `c71854292f7c367cc3b35939f88121d81945472f` (`b10012`)
- model: `gemma-4-31b-abliterated-Q4_K_M.gguf`
- topology: local `Vulkan0` plus private RPC `RPC0`, layer split `1,1`
- context: 327680 total, two 163840-token slots, Q4 KV
- Vision: 280–1120 image tokens with 1280 batch/ubatch/mtmd budget
- backup: `/mnt/ssd/llm-distributed/backups/vulkan-patch-20260721T183419Z`
- srv1 runtime archive SHA-256:
  `315bb1f0bf1f9cb3be03beeb17ae8cfff84458c2ab0f782ea14fa88646500bd8`
- source archive SHA-256:
  `7beab227a2fb139c65446a704dd30d0701fd453ee1630f47d34b2803432a4292`
- srv2 runtime archive SHA-256:
  `7046655ae6494e7905c06127e03020917e363d1c2e4308ba165853a83b2971cc`

The backup directory contains per-host manifests, hashes and `RESTORE.md`.

## Mesa/RADV capability candidate

The system driver is Mesa 25.0.7. Mesa 25.1 added cooperative-matrix support
for GFX12; the isolated Mesa 25.3.6 candidate exposes `KHR_coopmat` and bf16 on
both GPUs. The candidate is installed without replacing distribution files:

- srv1: `/mnt/ssd/llm-distributed/candidates/mesa-25.3.6-radv`
- srv2: `/opt/llm-rpc/candidates/mesa-25.3.6-radv`
- `libvulkan_radeon.so` SHA-256:
  `9611005ca79fd9471910ffd1737ed22fe7861b1412f0ac95a54262acf77197ba`

Authoritative references:

- [Mesa 25.1.0 release notes](https://docs.mesa3d.org/relnotes/25.1.0.html)
- [Mesa 25.3.6 release notes](https://docs.mesa3d.org/relnotes/25.3.6.html)
- [Mesa local installation guidance](https://docs.mesa3d.org/install.html)
- [RADV documentation](https://docs.mesa3d.org/drivers/radv.html)

The clean forced-output release gate passed.  Relative to system Mesa 25.0.7,
Mesa 25.3.6 raised median prefill from `171.168` to `336.265 tok/s`
(`1.9645x`, or `+96.45%`).  Median decode changed from `11.2673` to
`11.0638 tok/s` (`-1.81%`, inside the accepted 2% bound), and all three output
SHA-256 values matched exactly.  The source artifacts are
[`vulkan-baseline-20260721.json`](results/vulkan-baseline-20260721.json) and
[`vulkan-candidate-20260721.json`](results/vulkan-candidate-20260721.json).
Both nodes use the AMD `COMPUTE` profile plus the existing high DPM state; the
profile selector resolves the numeric sysfs index by name at boot instead of
assuming an index that may change between driver releases.

## llama.cpp b10076 candidate

Official tag `b10076`, commit
`305ba519ab61cdff8044922cba2347826a04453f`, was built unchanged with Vulkan,
RPC, server, Vision and backend tests.  The identical binary tree was copied to
both hosts; its normalized tree digest is
`94e044522e133313849c659de84407bc947f5309db44f8f49806df130bd5e097`.

On the accepted Mesa/COMPUTE baseline it is performance-neutral and preserves
the forced result exactly:

| Runtime | Median prefill | Median decode | Wall time | Output |
|---|---:|---:|---:|---|
| b10012 | 336.265 tok/s | 11.0638 tok/s | 71.380 s | control |
| b10076 | 336.260 tok/s | 11.0625 tok/s | 71.311 s | 3/3 SHA exact |

Ratios are `0.999985x` prefill and `0.999888x` decode.  The candidate is kept
because it does not regress the measured workload and is the clean base for
new Vulkan work, not because the version bump itself is faster.  Evidence:
[`vulkan-b10076-20260721.json`](results/vulkan-b10076-20260721.json).
After all experiments, the final clean binary passed the complete Vulkan
backend suite on both hosts: `15426/15426` on srv1 and `15426/15426` on srv2.
The consolidated record is
[`backend-tests-b10076-20260722.json`](results/backend-tests-b10076-20260722.json).

## Gemma 4 MTP experiment

The available 470M assistant GGUF was produced with an older schema.  Its
source SHA-256 is
`46eb446dc22ef584aae1d1ead6f5888a3f1fa71c5b8f5a8edce9c49846592228`.
`normalize_gemma4_mtp.py` created a new file without modifying the original:

- `general.architecture`: `gemma4_mtp` -> `gemma4-assistant`;
- all architecture metadata moved to the `gemma4-assistant.*` namespace;
- `backbone_embedding_length` became `embedding_length_out`;
- `nextn_predict_layers=4` was added;
- the two legacy projection tensors were renamed;
- the official 256-element F32 proportional-RoPE tensor was generated;
- every one of the 48 source tensor payloads was verified byte-identical.

The normalized candidate SHA-256 is
`77541d57fa9796a7b8c73780a21c8b30318b00ddeca3c4c5d1b5d91880040ca3`.
Both b10012 and b10076 exposed the same startup failure when the draft device
was limited to `Vulkan0`: Gemma 4 MTP shares late-layer target KV, but part of
that KV lives on `RPC0`.  Giving the draft scheduler
`--spec-draft-device Vulkan0,RPC0` fixed startup without a source patch.
Health passed with zero restarts and local VRAM increased by `339.05 MiB`.

Paired b10076 results with `MTP_N_MAX=1`:

| Workload | No MTP | MTP | Change | Exactness |
|---|---:|---:|---:|---|
| 10 realistic chat cases, median decode | 11.8065 tok/s | 14.7591 tok/s | **+25.01%** | 8/10 responses differed |
| 10 realistic chat cases, wall time | 75.009 s | 62.073 s | **-17.25%** | same comparison |
| forced single-path, median prefill | 336.260 tok/s | 320.818 tok/s | -4.59% | 3/3 hashes matched |
| forced single-path, median decode | 11.0625 tok/s | 7.1439 tok/s | **-35.42%** | 3/3 hashes matched |
| forced single-path, wall time | 71.311 s | 92.136 s | +29.20% | same comparison |

The first MTP profile was therefore **rejected for production**.  It has a real
natural-language speed opportunity, but fails the strict target-output gate
and becomes slower when the draft cannot predict the constrained token path.
Production remains `SPECULATIVE_MODE=none` (`ENABLE_MTP=0` is retained as a
backward-compatible alias).  Raw evidence:

- [`mtp-b10076-control-20260721.json`](results/mtp-b10076-control-20260721.json)
- [`mtp-b10076-mtp1-20260721.json`](results/mtp-b10076-mtp1-20260721.json)
- [`vulkan-b10076-mtp1-20260721.json`](results/vulkan-b10076-mtp1-20260721.json)
- [`mtp-b10012-control-20260721.json`](results/mtp-b10012-control-20260721.json)

A compact accepted/rejected matrix and an artifact index are available in
[`results/README.md`](results/README.md).

### Exact parameter sweep

A second sweep used 192-token responses and first repeated the clean control.
The two controls matched exactly in all 10 cases; median decode differed only
`+0.21%`, establishing that the later output differences were caused by the
speculative profile rather than baseline nondeterminism.

| Profile | Median decode change | Wall change | Exactness | Decision |
|---|---:|---:|---|---|
| MTP `N_MAX=1/2/4/8`, `p_min=0` | +24.19% to +24.72% | -17.30% to -17.43% | same 8/10 cases differ for every N | reject |
| MTP `N_MAX=1`, `p_min=0.25` | +24.78% | -17.28% | 8/10 differ | reject |
| MTP `N_MAX=1`, `p_min=0.50` | **+25.62%** | -16.61% | 8/10 differ | reject |
| MTP `N_MAX=1`, `p_min=0.80` | +17.71% | -11.71% | 7/10 differ | reject |
| MTP `N_MAX=1`, `p_min=1.00` | -23.44% | +28.05% | 6/10 differ | reject |
| MTP CPU draft sampling | +19.07% | -13.64% | 8/10 differ | reject |
| `ngram-simple` 12/48/1, cold/warm | +0.006% / +0.263% | -0.06% / -0.33% | 10/10 exact | reject: noise/below gate |
| `ngram-mod` 48/64/24, warm | **+57.05%** | **-32.34%** | 7/10 differ | reject |

Shorter ngram lookups increased false matches: `ngram-simple` 4/16/1 changed
6/10 outputs and regressed throughput, while `ngram-mod` 4/16/8 changed one
cold and three warm outputs without a median speed gain.  Offloading draft
sampling to the CPU did not restore target-output identity.  The complete
machine-readable comparison is
[`speculative-sweep-b10076-20260722.json`](results/speculative-sweep-b10076-20260722.json).
No exact candidate reached the 5% gate, so `SPECULATIVE_MODE=none` is final.

## CUDA ideas adapted to native Vulkan

CUDA is a source of algorithmic hypotheses, not portable kernel code.

| CUDA/RDNA4 observation | Native Vulkan treatment | Result |
|---|---|---|
| Q4_K MMVQ uses an architecture-specific warp/row mapping. | Change only Vulkan's `rm_kq`, rebuild GLSL/SPIR-V and compare the exact same model/output. | Rejected on both bases: b10076 variants ranged from -0.06% to +0.53% prefill. |
| Large quantized matmuls benefit from contiguous tile access and cooperative-matrix-friendly layouts. | Backport/adapt upstream Vulkan transposed-A K-quant layout, preserving b10012 CM1/CM2/scalar dispatch boundaries. | Rejected: +1.09% prefill but -17.08% decode. |
| Tiling and register pressure must be architecture-specific. | Preserve b10012 GFX1200 `BM/BN`, `WMITER` and alignment specialization instead of copying CUDA launch constants. | Baseline invariant. |
| Fusion/speculation can reduce launch or decode overhead. | Profile first; implement only a Vulkan-native candidate with an exact control. | Persistent global FA improved prefill 2.56% and wall time 1.25%; retained as research-only. |

The rejected transposed-A candidate remains reproducible on both nodes at
`llama-b10012-kquant-transpose`; its normalized tree digest is
`702029409645bc268c040e0b82f77582a2e13e06283cd28050079a0a1fec938d`.
See [`../patches/llama.cpp-b10012/README.md`](../patches/llama.cpp-b10012/README.md)
and upstream [llama.cpp PR #22970](https://github.com/ggml-org/llama.cpp/pull/22970).

## Reproducible A/B

Run only after production has remained idle and retain both JSON artifacts:

```bash
python3 llm_ops/vulkan/benchmark_vulkan.py run \
  --label BASELINE --output docs/results/vulkan-baseline-20260721.json
python3 llm_ops/vulkan/benchmark_vulkan.py run \
  --label CANDIDATE --output docs/results/vulkan-candidate-20260721.json
python3 llm_ops/vulkan/benchmark_vulkan.py compare \
  docs/results/vulkan-baseline-20260721.json \
  docs/results/vulkan-candidate-20260721.json \
  --minimum-prefill-speedup 1.05 --maximum-generation-regression 0.02
```

Deployments share `/run/lock/gemma-vulkan-deploy.lock`, require an idle window,
restart the RPC worker before the primary, verify health, and automatically
roll back on startup failure:

```bash
sudo llm_ops/vulkan/deploy-mesa-radv.sh enable
sudo llm_ops/vulkan/deploy-llama-candidate.sh enable kquant-transpose
sudo llm_ops/vulkan/deploy-llama-candidate.sh rollback
sudo llm_ops/vulkan/deploy-mesa-radv.sh rollback
```

Final accepted/rejected measurements and production E2E evidence are appended
only after the corresponding commands have completed successfully.

## Vulkan timestamp profile

The b10076 Vulkan timestamp logger was run for one 4095-token prefill plus 64
decode tokens, then removed and the service restarted normally.  The largest
local-GPU buckets were:

| Total GPU time | Calls | Operation |
|---:|---:|---|
| 823.389 ms | 3534 | `MUL_MAT_VEC q4_K`, 21504x5376 |
| 505.041 ms | 62 | `MUL_MAT q4_K`, 21504x1276x5376 |
| 337.783 ms | 30 | `MUL_MAT q6_K`, 5376x1280x21504 |
| 288.643 ms | 855 | `MUL_MAT_VEC q6_K`, 5376x21504 |
| 285.898 ms | 32 | `MUL_MAT q4_K`, 5376x1280x21504 |
| 253.399 ms | 5 | global `FLASH_ATTN_EXT` prefill |
| 212.339 ms | 912 | `MUL_MAT_VEC q4_K`, 5376x21504 |

This proves that Q4_K/Q6_K matvec is the decode bottleneck and justifies
testing row mapping and clean-room activation-load reuse before broader fusion.
The request-level artifact is
[`vulkan-b10076-profile-run-20260721.json`](results/vulkan-b10076-profile-run-20260721.json).

## Native RDNA4 FA4-inspired attention

The b10076 cooperative-matrix Vulkan kernel already performs tiled online
softmax and fuses QK, probability normalization and PV into one dispatch.  The
work therefore focused on Gemma 4's alternating head dimensions instead of
trying to translate Hopper-only TMA, WGMMA or warp-specialization code:

1. **Per-layer dispatch:** local `head_dim=256` and global `head_dim=512`
   candidates are selected independently on GFX1200.
2. **Tiled online softmax:** retained inside `flash_attn_cm1.comp`; no full
   attention matrix is materialized.
3. **Cooperative matrix:** KHR cooperative matrices are provided by the
   isolated Mesa/RADV 25.3.6 runtime.
4. **LDS reuse:** local K/V staging was measured and rejected.  A global F16
   K tile alone needs 64 KiB; double-buffering it needs 128 KiB before V and
   reduction state, exceeding GFX1200's 64 KiB workgroup limit.
5. **Persistent workgroups / split-K:** `Br=32` reuses each global K/V tile for
   two 16-row Q tiles.  Upstream dynamic split-K remains enabled; profiling did
   not show a global-attention workgroup shortage that justified forcing extra
   reductions.
6. **QK → softmax → V fusion:** preserved in the persistent kernel rather than
   adding intermediate buffers or launch boundaries.

All global `head_dim=512` candidates passed `112/112` targeted backend tests on
both GPUs.  Forced-output results relative to clean b10076 were:

| Candidate | Median prefill | Median decode | Wall time | Output | Decision |
|---|---:|---:|---:|---|---|
| Local `head_dim=256` LDS staging | -1.673% | -0.327% | +1.142% | 3/3 exact | reject |
| Global scalar dispatch | -3.152% | +0.513% | +1.389% | 3/3 exact | reject |
| Global `Bc=128`, eight wave64 subgroups | +0.460% | -0.380% | -0.103% | 3/3 exact | reject |
| Global persistent `Br=32` | **+2.557%** | +0.056% | **-1.253%** | 3/3 exact | research-only; below 5% gate |

The clean b10076 runtime therefore remains the production choice.  Reproducible
patches, shader/resource rationale and the complete small-candidate matrix are
in [`../patches/llama.cpp-b10076/README.md`](../patches/llama.cpp-b10076/README.md).

## Operational capacity monitoring

Build worktrees, Mesa prefixes, model variants and JSON evidence can fill the
model disk without changing service health immediately.  The final production
check records `df -P` for `/mnt/ssd` on srv1 and `/opt` on srv2 alongside VRAM,
`NRestarts`, `/health`, `/slots` and cgroup OOM counters.  Treat either less
than 15% free disk or less than the space required for one complete rollback
runtime plus model copy as an alert; delete rejected build directories only
after their patch and result artifact are committed.

Minimal live checks are:

```bash
df -P /mnt/ssd                         # srv1
df -P /opt                             # srv2
systemctl show llm-gemma4-primary.service -p NRestarts -p MemoryCurrent
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/slots
```

Disk cleanup is deliberately not automatic: deleting the active candidate,
the preserved rollback tree or an uncommitted evidence file would be more
damaging than a warning.

## Final production E2E

The final clean b10076 runtime, not a shader or speculative candidate, passed
the complete production path on 2026-07-22:

| Check | Result |
|---|---|
| Text | 22 prompt tokens, 3 completion tokens, non-empty answer |
| Vision | 2048×2048 PNG, 1117 prompt tokens, 50 completion tokens, correct geometric description |
| Two long slots | **159012 prompt + 16 completion tokens in each slot** |
| Long-request overlap wall time | 1876.49 s |
| RPC/GPU use | both GFX1200 GPUs reached 100% busy |
| Minimum free VRAM | srv1 1,270,198,272 bytes (1.183 GiB); srv2 2,144,182,272 bytes (1.997 GiB) |
| Service state | same PIDs before/after, `NRestarts=0` on both hosts |
| Memory events | `oom=0`, `oom_kill=0`, `max=0` |
| Power state | `high` DPM and `COMPUTE` profile on both hosts |
| Health / slots | health OK before/after; two 163840-token slots idle after completion |
| Disk | srv1 model disk 36% used; srv2 root 31% used |

The two long requests were submitted concurrently and occupied separate
163840-token slots.  With the production `batch-size=1280`, llama.cpp serializes
large prompt-prefill chunks rather than evaluating two 159K prompts fully in
parallel.  Restartless slot KV reuse was visible in the final run (35,535
cached tokens in one slot and 159,011 in the other); both requests nevertheless
reported the full 159,012-token prompt and completed successfully.  This is a
scheduler/latency characteristic, not a capacity failure.  Long-client timeouts
must allow for sequential prefill at this context size.

The sanitized raw record is
[`production-e2e-b10076-20260722.json`](results/production-e2e-b10076-20260722.json).
