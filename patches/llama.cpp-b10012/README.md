# llama.cpp b10012 Vulkan candidate patches

Every patch in this directory targets the exact production base commit
`c71854292f7c367cc3b35939f88121d81945472f` (llama.cpp tag `b10012`).  Build
them with `llm_ops/vulkan/build-llama-b10012-candidate.sh`; do not apply them to
an arbitrary upstream revision.

| Candidate | Origin and intent | Production decision |
|---|---|---|
| `0001-vulkan-rdna4-rm-kq-1.patch` | Clean-room experiment based on the RDNA4 CUDA MMVQ row/warp mapping: reduce Vulkan K-quant rows per workgroup from two to one. | Rejected. A forced-output A/B measured only about +0.43% prefill and no decode improvement. |
| `0002-vulkan-kquant-transposed-a-cm1.patch` | Backport/adaptation of upstream Vulkan PR [#22970](https://github.com/ggml-org/llama.cpp/pull/22970). Repack Q4_K/Q5_K/Q6_K/Q5_1 weights into a block-major layout and use dedicated GLSL/SPIR-V cooperative-matrix pipelines. | Candidate. Requires backend correctness, exact-output model A/B, Vision, RPC and stability gates before production use. |

The transposed-A patch preserves b10012's dynamic alignment specialization,
dot2 path, native OCP FP4 path and CM2/scalar fallbacks.  Its new shaders are
restricted to the CM1 capability branch, matching the upstream design.  It
also records which tensors were actually repacked, so chunked/2-D/host-pointer
uploads cannot accidentally select the transposed pipeline.

`GGML_VK_NO_TRANSPOSE_A=1` disables the new layout.  This provides a same-binary
A/B control and avoids attributing unrelated compiler or build differences to
the patch.

The CUDA source is used only to identify algorithmic hypotheses. CUDA kernels
are not copied into the Vulkan backend: each candidate is independently
implemented in C++ plus GLSL, compiled to SPIR-V, and validated on GFX1200.
