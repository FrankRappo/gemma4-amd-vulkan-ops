# RDNA4-native lossless Q4_K decode kernel proposal

**Status:** design proposal; no production change  
**Target:** Gemma 4 31B Abliterated Q4_K_M on two GFX1200 GPUs  
**Pinned starting point:** llama.cpp `b10076`, Mesa/RADV `25.3.6`  
**Prepared:** 2026-07-23

## Executive summary

The remaining decode bottleneck is the Vulkan Q4_K/Q6_K matrix-vector path,
not Flash Attention. Small changes to row mapping, scale sharing, activation
reuse and attention tiling have already been measured and did not materially
improve generation. The next credible software-only upgrade is a new
GFX1200-specific Q4_K path that changes the GPU data layout and execution
strategy while preserving the model, quantized values, KV-cache format and
generated answers.

The proposed work has four parts:

1. add a lossless, GPU-native Q4_K layout produced while weights are uploaded;
2. add shape-specialized GFX1200 shaders for Gemma's dominant matrix sizes;
3. autotune single-slot and two-slot variants without changing arithmetic
   precision;
4. retain the existing Vulkan path as an immediate runtime fallback.

A candidate is a production success only if it passes backend reference tests,
keeps deterministic text/tool/Vision outputs unchanged, preserves the two-slot
160K context profile and improves median decode by at least 10%. A
"breakthrough" result is defined as at least 15% end-to-end decode improvement,
not merely a kernel microbenchmark gain.

## Current production baseline

The immutable comparison profile is:

| Component | Value |
|---|---|
| Target model | `gemma-4-31b-abliterated-Q4_K_M.gguf` |
| llama.cpp | official `b10076`, commit `305ba519ab61cdff8044922cba2347826a04453f` |
| Vulkan driver | isolated Mesa/RADV `25.3.6` |
| Devices | local `Vulkan0` plus private `RPC0`, layer split `1,1` |
| Context | `327680` total, two `163840`-token slots |
| KV cache | Q4 K and Q4 V |
| Vision | adaptive 280–1120 image tokens |
| Prompt cache | disabled, `--cache-ram 0` |
| Single-request generation | approximately `11.7 token/s` in the capacity probe |
| Two-request aggregate | `19.272 token/s` |
| Minimum observed free VRAM | approximately `1.20 GiB` |

The exact baseline must be rerun immediately before development because kernel,
driver, clocks, production traffic and RPC state can invalidate a historical
comparison.

## Evidence for the target

The existing Vulkan timestamp profile for one 4095-token prefill and 64 decode
tokens recorded the following dominant local-GPU buckets:

| Total GPU time | Calls | Operation |
|---:|---:|---|
| 823.389 ms | 3534 | `MUL_MAT_VEC q4_K`, `21504x5376` |
| 288.643 ms | 855 | `MUL_MAT_VEC q6_K`, `5376x21504` |
| 212.339 ms | 912 | `MUL_MAT_VEC q4_K`, `5376x21504` |

This makes Q4_K/Q6_K matvec the strongest remaining decode target. Attention
work is lower priority: the best exact FA4-inspired candidate improved prefill
by 2.557% but decode by only 0.056%.

The complete profile and rejected-candidate record is in
[`vulkan-rdna4-performance.md`](vulkan-rdna4-performance.md).

## Why Q4_K is expensive

Upstream llama.cpp defines a Q4_K super-block as 256 weights grouped into eight
32-weight sub-blocks. It contains:

- two FP16 super-block factors, `d` and `dmin`;
- 12 bytes containing packed 6-bit scales and minimums;
- 128 bytes containing 256 four-bit quantized values.

The total is 144 bytes, or effectively 4.5 bits per weight. The format is
storage-efficient but requires non-trivial bit extraction and scaling during
every matrix-vector multiplication.

The generic Vulkan shader must repeatedly:

1. calculate block and tensor offsets;
2. load packed Q4 values and packed scale/min metadata;
3. extract low and high nibbles;
4. reconstruct the 6-bit scale and minimum values;
5. convert values into the active floating-point type;
6. multiply them by the activation vector;
7. reduce partial FP32 sums across the subgroup or workgroup.

Authoritative upstream references:

- [`block_q4_K` layout](https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-common.h)
- [current Q4_K Vulkan matvec shader](https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec_q4_k.comp)

The pinned `b10076` source remains the implementation authority for this work;
`master` is referenced only to explain the current upstream design.

## Non-negotiable quality constraints

This upgrade must not obtain speed by changing the model's effective
mathematics or available context.

The following are prohibited:

- changing or replacing the GGUF model;
- re-quantizing Q4_K weights;
- quantizing activations to Q8_1 for the production candidate;
- changing KV-cache types;
- reducing context, Vision limits or output limits to improve a benchmark;
- enabling approximate math or lower-precision accumulation;
- enabling speculative decoding;
- changing prompts, templates, samplers or stop conditions.

The proposed layout transformation is allowed only if it is a bit-preserving
permutation or lossless unpacking of existing Q4_K metadata. The original GGUF
file remains unchanged and its digest remains part of every result artifact.

FP32 accumulation must be retained. A different reduction order can still
produce small floating-point differences, so output identity is an explicit
release gate rather than an assumption.

## Why the integer-dot shortcut is not the primary design

llama.cpp also contains an MMVQ path using `GL_EXT_integer_dot_product` and
`dotPacked4x8EXT`. It pairs Q4_K weights with Q8_1-quantized activations. That
can reduce the number of floating-point multiply-add instructions, but it adds
activation quantization and therefore does not satisfy the strict
same-output-first requirement.

It is also not automatically faster on AMD. Upstream issue
[#21151](https://github.com/ggml-org/llama.cpp/issues/21151) reports that the
Q8_1 MMVQ path for K-quants can be much slower than native floating-point
dequantization on an RDNA3 device.

The first production-oriented candidate therefore keeps F16/F32 activations
and FP32 accumulation. Integer-dot experiments, if performed at all, remain a
separate research lane and cannot be promoted without independently passing
the exact-output gate.

## Proposed architecture

### 1. Lossless GPU-native Q4_K layout

The first layout candidate keeps the same 144-byte size and only changes the
order in which Q4 values and metadata appear in the Vulkan weight buffer. It
must be arranged for coalesced loads by one GFX1200 wave rather than for direct
GGUF serialization.

Conceptually:

```text
GGUF block:
    [d, dmin][packed scales/mins][packed q values]

GPU decode block:
    [wave-major q groups][wave-major packed metadata][d, dmin]
```

Requirements:

- no permanent duplicate copy of the complete model;
- transform while uploading into the final Vulkan allocation;
- byte-for-byte reversible mapping in a host-side unit test;
- no additional per-request allocation;
- no change to the source GGUF or CPU backend representation;
- use the original path for non-GFX1200 devices and unsupported tensor shapes.

A second candidate may expand the 12 packed scale/min bytes into 16 `uint8`
values to remove repeated 6-bit extraction. That adds four bytes per Q4_K
super-block and must not proceed until a full-model VRAM estimate proves that
the measured reserve remains safe. It is not the default design.

### 2. GFX1200 shape-specialized shader family

Generate independent SPIR-V variants for the dominant Gemma shapes rather than
using one universal parameter set:

```text
Q4_K 21504 x 5376
Q4_K  5376 x 21504
Q6_K  5376 x 21504       # follow-up only after Q4_K proves the method
```

The Q4_K variants should cover:

- one and two active columns/sequences;
- wave/subgroup sizes exposed by the device;
- two, four and possibly eight output rows per workgroup;
- subgroup-only and hybrid reduction where valid;
- different values-per-lane and blocks-per-iteration settings.

Specialized shaders may remove dynamic tail handling, repeated integer
division and generic broadcast branches when the exact dimensions make them
unnecessary.

### 3. Controlled reuse without excessive register pressure

The current shader already supports multiple columns through `NUM_COLS` and
reuses decoded weight values across the inner column loop. The upgrade must
not claim this as a new feature.

The real task is to measure whether a dedicated `NUM_COLS=2` variant can retain
that reuse without doubling live activation state and spilling VGPRs. A
two-slot variant is accepted only if it raises aggregate throughput without
materially worsening individual request latency.

Likewise, computing multiple output rows per workgroup is useful only while
occupancy remains high. More reuse is not automatically faster if the compiled
shader consumes too many registers.

### 4. Runtime dispatch and autotuning

Do not hard-code one layout/workgroup choice for every GFX1200 device. At
candidate initialization:

1. verify the exact device/vendor/driver capability tuple;
2. run a bounded kernel-only benchmark for the known shapes;
3. reject any variant that fails the backend reference comparison;
4. select the fastest correct variant separately for one and two columns;
5. cache the result using GPU UUID, driver version, llama.cpp commit and shader
   digest as the key.

Autotuning must be bounded and optional. Failure, timeout or an unknown device
selects the unchanged upstream pipeline.

Proposed feature controls:

```text
GGML_VK_GFX1200_Q4K=off|auto|on
GGML_VK_GFX1200_Q4K_LAYOUT=packed|scales_u8
GGML_VK_GFX1200_Q4K_TUNE_CACHE=/path/to/cache.json
```

Names are provisional and must follow the pinned llama.cpp backend's existing
configuration conventions before implementation.

### 5. Optional graph fusion after kernel success

Gemma's gate and up projections consume the same input activation before the
activation/multiply step. A later experiment may combine dispatch or buffer
handling for:

```text
gate projection ─┐
                 ├─ activation and multiply
up projection ───┘
```

This is intentionally out of the first kernel patch. It changes GGML graph
boundaries and is harder to validate and upstream. It should begin only if the
standalone Q4_K shader produces a measurable result and profiling then shows
dispatch or intermediate-buffer traffic as the next bottleneck.

## Expected source surface

The exact file list depends on the pinned tree, but the likely implementation
surface is:

```text
ggml/src/ggml-vulkan/ggml-vulkan.cpp
ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec_q4_k.comp
ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec_base.glsl
ggml/src/ggml-vulkan/vulkan-shaders/vulkan-shaders-gen.cpp
ggml/src/ggml-vulkan/...
```

The weight-upload transformation must remain inside the Vulkan backend. GGUF
parsing and CPU tensors should not acquire an RDNA4-specific representation.

Each conceptual change must be an independent patch:

1. instrumentation and microbenchmark only;
2. same-layout shape specialization;
3. lossless packed-layout upload and matching shader;
4. optional unpacked-scale layout;
5. autotuner/dispatch;
6. optional two-column specialization;
7. optional fusion.

This separation makes regressions attributable and rollback immediate.

## Execution plan

### Phase 0 — reproduce and expand the profile

- rebuild clean `b10076` on both nodes;
- verify identical runtime tree digests;
- repeat the existing deterministic request benchmark;
- capture Vulkan timestamps on both the primary and RPC worker;
- measure one-slot and two-slot decode independently;
- record RPC wall time, GPU busy time and CPU submission time;
- retain clocks, power profile, driver and thermal telemetry.

Stop if the historical baseline cannot be reproduced within normal variance.

### Phase 1 — kernel-only harness

- add fixed-shape Q4_K matvec cases matching Gemma dimensions;
- generate deterministic Q4_K blocks and F16/F32 activation vectors;
- compare candidate output against CPU and clean Vulkan references;
- measure kernel time without HTTP, model loading or RPC noise;
- emit compiled shader properties where tooling permits, especially register
  pressure, occupancy-related limits and workgroup dimensions.

This phase prevents a slow or incorrect shader from reaching the complete
model benchmark.

### Phase 2 — same-layout specialization

- keep the original Q4_K bytes;
- add fixed-shape dispatch variants;
- sweep rows per workgroup, subgroup reduction and iteration count;
- test one active column and two active columns separately;
- discard variants that do not improve kernel time by at least 5%.

This is the cheapest way to determine whether dispatch specialization alone
has remaining headroom.

### Phase 3 — lossless packed layout

- implement a reversible host reference pack/unpack function;
- transform weights during Vulkan upload;
- add matching shader loads;
- verify logical Q4 values, scales and minimums before testing dot products;
- initially enable only selected Q4_K tensors behind an explicit flag;
- measure memory overhead and startup time.

The generic transposed-A candidate previously regressed decode by 17.08%.
Promotion therefore depends entirely on measured decode behavior; layout
locality must not be inferred from prefill results.

### Phase 4 — whole-model and dual-host evaluation

- apply the exact same runtime tree to both Vulkan/RPC nodes;
- run single-request text decode;
- run two concurrent text requests;
- run the 36K long-context fixture;
- run dense 1120-token Vision;
- run concurrent Vision plus text;
- run Claw tool-call fixtures;
- inspect service restarts, cgroup OOM events and minimum free VRAM.

### Phase 5 — autotuning and production packaging

- add bounded startup/offline tuning;
- cache only reference-clean selections;
- package the patch, build metadata and runtime tree digest;
- document enable, disable and rollback commands;
- perform a clean reboot and end-to-end verification.

## Verification matrix

### Backend correctness

- targeted Q4_K matvec cases for each shape and column count;
- odd/tail dimensions use the upstream fallback;
- full Vulkan backend suite on both GPUs;
- reversible layout tests for every Q4_K block field;
- NaN, infinity and extreme activation fixtures;
- no device validation errors.

The last clean baseline completed `15426/15426` Vulkan backend tests on each
host. A candidate must meet or exceed the applicable test count from its pinned
tree.

### Output identity

- fixed model digest;
- fixed chat template and system prompt;
- temperature zero and fixed seed;
- at least 100 representative text/Claw prompts;
- exact generated-token sequence comparison;
- exact tool name and JSON argument comparison;
- deterministic Vision extraction fixtures;
- repeated clean controls to distinguish candidate differences from baseline
  nondeterminism.

Any repeatable token or tool-call difference rejects the production candidate,
even if an aggregate quality score appears unchanged.

### Performance

Report medians and dispersion, not the best run:

- kernel-only Q4_K time by shape;
- prompt processing token/s;
- single-request generation token/s;
- two-request individual and aggregate token/s;
- time to first token;
- total wall time;
- primary and RPC GPU busy time;
- CPU submission time and RPC wait time.

All A/B pairs require a continuous idle interval and the same clocks,
temperature band, model, context and request fixtures.

### Capacity and stability

- two effective `163840`-token slots remain exposed;
- Claw compaction remains at `110000` input tokens;
- `--cache-ram 0` remains active;
- dense Vision succeeds at 1120 image tokens;
- minimum free VRAM remains above the existing 1 GiB safety guard;
- zero cgroup `oom` and `oom_kill` events;
- zero Vulkan device loss;
- zero unexpected service restarts.

## Decision gates

| Result | Decision |
|---|---|
| Any backend/reference or output mismatch | Reject immediately |
| Kernel improvement below 5% | Reject the variant |
| End-to-end decode improvement below 5% | Reject as noise/insufficient |
| Decode +5% to +10%, exact and stable | Research-only |
| Decode at least +10%, exact and stable | Production candidate |
| Decode at least +15%, exact and stable | Breakthrough candidate |
| Prefill regression greater than 2% | Reject unless separately justified and approved |
| Individual latency regression greater than 5% in the two-slot profile | Reject two-slot variant |
| Minimum free VRAM below 1 GiB | Reject |

The target ranges are:

```text
single stream:
    current approximately 11-12 token/s
    production target approximately 13 token/s or better
    stretch target approximately 14-15 token/s

two concurrent streams:
    current 19.272 token/s aggregate
    production target at least 21 token/s aggregate
    stretch target approximately 22-25 token/s aggregate
```

These are engineering targets, not promised outcomes.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| More rows/columns increase VGPR pressure and reduce occupancy | Compile multiple small variants; select only measured winners |
| Repacked layout helps loads but harms cache behavior | Compare same-layout specialization first; preserve instant fallback |
| Extra metadata exceeds the tight VRAM reserve | Prefer same-size permutation; require full capacity retest before expanded metadata |
| Different reduction order changes logits | Retain FP32 accumulation and require exact token/tool output |
| Local GPU improves but RPC GPU regresses | Profile and benchmark both nodes independently |
| Startup autotuning is slow or unstable | Bound duration, cache by exact build/device tuple, fall back on failure |
| Driver-specific behavior changes after Mesa upgrade | Include driver and shader digest in cache key; invalidate automatically |
| Patch becomes difficult to rebase | Keep each layer independent and avoid changes outside the Vulkan backend |
| A synthetic kernel win disappears end to end | Require complete text, Vision, RPC and two-slot gates before promotion |

## Rollback

Production never overwrites the preserved clean runtime. Candidate binaries
are installed in a separate versioned directory on both nodes.

Rollback order:

1. stop admitting new model requests;
2. wait for both `/slots` entries to become continuously idle;
3. restart the RPC worker with the clean runtime;
4. restart the primary server with the clean runtime;
5. verify runtime tree digests, `/health`, `/slots` and effective context;
6. run deterministic text and Vision smoke tests;
7. retain rejected patch and result artifacts for future comparison.

The runtime feature flag must also permit disabling the new path without
changing the binary, but the known-clean binary remains the authoritative
rollback.

## Effort and stop condition

Estimated engineering effort with access to both GFX1200 nodes:

| Work | Estimate |
|---|---:|
| Fresh baseline and dual-host profiling | 2–4 hours |
| First lossless Q4_K prototype | 8–16 hours |
| Reference fixes and dispatch integration | 4–8 hours |
| Shape/one-slot/two-slot tuning | 12–24 hours |
| RPC, Vision, Claw and stability validation | 6–10 hours |
| Total bounded research budget | approximately 30–60 engineering hours |

Expected checkpoints:

- first measured candidate: about one concentrated engineering day;
- evidence for a `>10%` stop/go decision: approximately 2–3 days;
- production-quality packaging of a successful candidate: approximately
  4–7 days.

Stop this lane when any of the following is true:

1. a verified production candidate satisfies every gate;
2. three materially different kernel/layout strategies fail to reach 5%
   kernel improvement;
3. all faster candidates fail exact output or capacity requirements;
4. profiling proves RPC or another non-Q4_K component dominates after the
   first improvement.

Failure to reach the target is a valid result. It prevents additional
micro-patches from being promoted on noise and identifies the next measured
bottleneck.

## Artifact contract

Every candidate should leave:

```text
patches/llama.cpp-<tag>/<sequence>-vulkan-gfx1200-q4k-<name>.patch
docs/results/q4k-<name>-kernel-<date>.json
docs/results/q4k-<name>-single-<date>.json
docs/results/q4k-<name>-parallel2-<date>.json
docs/results/q4k-<name>-production-e2e-<date>.json
```

Each result must include:

- source commit and patch digest;
- normalized runtime tree digest for both nodes;
- model and projector digests;
- Mesa/RADV version;
- device UUIDs and clocks/profile state;
- complete launch arguments;
- output hashes;
- kernel and request metrics;
- VRAM, restart and cgroup memory evidence;
- decision and rollback target.

This proposal changes no production state. Implementation begins only in
isolated worktrees and candidate runtime directories, with the existing clean
`b10076` deployment preserved throughout.
