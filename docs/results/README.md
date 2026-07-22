# Performance result index

Measured on 2026-07-21 and 2026-07-22 with Gemma 4 31B Q4_K_M split across two GFX1200
GPUs.  JSON files in this directory are the raw request-level evidence; the
method, non-regression gates, backups and deployment status are documented in
[`../vulkan-rdna4-performance.md`](../vulkan-rdna4-performance.md).

## Current decisions

| Candidate | Main measured result | Decision |
|---|---|---|
| Mesa/RADV 25.3.6 + AMD `COMPUTE` profile | Prefill `171.168 -> 336.265 tok/s` (`+96.45%`); decode `-1.81%`; 3/3 forced-output hashes exact | **Accepted** |
| Official llama.cpp b10076 | Prefill and decode both within `0.02%` of b10012; 3/3 hashes exact | Retained as the clean Vulkan development base; version upgrade alone is neutral |
| Gemma 4 MTP, `MTP_N_MAX=1` | Realistic median decode `11.8065 -> 14.7591 tok/s` (`+25.01%`), wall time `-17.25%` | **Rejected for production:** 8/10 natural-language responses differed and the forced single-path gate regressed |
| Exact speculative sweep | Controls exact 10/10; fastest exact candidate only `+0.263%`; MTP up to `+25.62%` and warm ngram-mod `+57.05%` changed outputs | **Rejected; production `SPECULATIVE_MODE=none`** |
| Vulkan K-quant transposed-A candidate | Prefill `+1.09%`, decode `-17.08%` | **Rejected** |
| Best FA4-inspired candidate: global persistent `Br=32` | Prefill `+2.557%`, decode `+0.056%`, wall time `-1.253%`, 112/112 global-FA tests on each GPU | Research-only: correct, but below the 5% deployment gate |

Production remains on Mesa/RADV 25.3.6 with llama.cpp b10076 and
`SPECULATIVE_MODE=none` (`ENABLE_MTP=0` remains compatible).  Every small
Vulkan shader candidate has now been evaluated; none replaced clean b10076.
The final Text, Vision, RPC and dual-159K production E2E completed with zero
restarts or OOM events.

## MTP evidence

The available legacy 470M Gemma 4 assistant was normalized without changing
the original file or any of its 48 tensor payloads.  The normalized candidate
started correctly only when the speculative scheduler could see both
`Vulkan0` and `RPC0`, because it reuses late-layer target KV that spans both
hosts.  It consumed an additional `339.05 MiB` of local VRAM and caused no
service restarts during the benchmark.

| Artifact | Purpose |
|---|---|
| [`mtp-b10012-control-20260721.json`](mtp-b10012-control-20260721.json) | Original b10012 realistic-workload control |
| [`mtp-b10076-control-20260721.json`](mtp-b10076-control-20260721.json) | Paired b10076 realistic-workload control |
| [`mtp-b10076-mtp1-20260721.json`](mtp-b10076-mtp1-20260721.json) | b10076 realistic workload with MTP enabled |
| [`vulkan-b10076-20260721.json`](vulkan-b10076-20260721.json) | b10076 forced single-path control |
| [`vulkan-b10076-mtp1-20260721.json`](vulkan-b10076-mtp1-20260721.json) | MTP forced single-path result |

The realistic result demonstrates a genuine speculative-decoding speed
opportunity, but it is not an accepted exact-output optimization.  On the
forced single-path workload MTP reduced median decode from `11.0625` to
`7.1439 tok/s` (`-35.42%`) and increased wall time by `29.20%`.  This is why
the feature remains available for future experiments but disabled by default.

The expanded 2026-07-22 sweep varied MTP `N_MAX`, `p_min`, backend sampling,
ngram lookup lengths, and cold/warm cache state.  The paired controls were
exact in all 10 cases.  No exact candidate reached the 5% gate; the complete
summary and per-candidate artifact names are in
[`speculative-sweep-b10076-20260722.json`](speculative-sweep-b10076-20260722.json).

## Other evidence

| Artifact | Purpose |
|---|---|
| [`vulkan-baseline-20260721.json`](vulkan-baseline-20260721.json) | System Mesa 25.0.7 baseline |
| [`vulkan-candidate-20260721.json`](vulkan-candidate-20260721.json) | Accepted isolated Mesa/RADV 25.3.6 candidate |
| [`vulkan-b10076-profile-run-20260721.json`](vulkan-b10076-profile-run-20260721.json) | Request paired with the Vulkan timestamp profile |
| [`vulkan-b10076-q4k-activation-cache-20260721.json`](vulkan-b10076-q4k-activation-cache-20260721.json) | Q4_K activation-tile reuse, below gate |
| [`vulkan-b10076-q4k-mmvq32-20260721.json`](vulkan-b10076-q4k-mmvq32-20260721.json) | Q4_K 32-value tile request result; rejected by backend reference gate |
| [`vulkan-b10076-q4k-scale-shuffle-20260721.json`](vulkan-b10076-q4k-scale-shuffle-20260721.json) | Subgroup XOR scale broadcast |
| [`vulkan-b10076-q4k-scale-quad-20260721.json`](vulkan-b10076-q4k-scale-quad-20260721.json) | Subgroup quad scale sharing |
| [`vulkan-b10076-fa-local-lds-20260721.json`](vulkan-b10076-fa-local-lds-20260721.json) | Local head_dim=256 LDS staging regression |
| [`vulkan-b10076-fa-global-scalar-20260722.json`](vulkan-b10076-fa-global-scalar-20260722.json) | Global head_dim=512 scalar-dispatch regression |
| [`vulkan-b10076-fa-global-bc128-20260722.json`](vulkan-b10076-fa-global-bc128-20260722.json) | Correct global Bc=128 candidate, below gate |
| [`vulkan-b10076-fa-global-br32-20260722.json`](vulkan-b10076-fa-global-br32-20260722.json) | Correct persistent Br=32 candidate; best shader result, research-only |
| [`backend-tests-b10076-20260722.json`](backend-tests-b10076-20260722.json) | Clean b10076 full Vulkan suite: 15426/15426 on each GFX1200 GPU |
| [`production-e2e-b10076-20260722.json`](production-e2e-b10076-20260722.json) | Text, 1120-token Vision path, RPC, two 159012-token slots, VRAM, disk and stability evidence |
| [`context-parallel-20260720.json`](context-parallel-20260720.json) | Context/two-slot capacity measurements |

The complete patch-to-result mapping, including all Q4_K row mapping and
attention candidates, is in
[`../../patches/llama.cpp-b10076/README.md`](../../patches/llama.cpp-b10076/README.md).
