# Deployment sequence

1. Install matching llama.cpp Vulkan runtime builds on both GPU nodes.
2. Bind the RPC worker only to a trusted private network.
3. Start the remote RPC worker and verify its port locally.
4. Start the primary multimodal server bound to localhost.
5. Verify `/health`, `/props`, slot count, effective context, and GPU memory.
6. Run deterministic text and Vision fixtures.
7. Start the Telegram tunnel and bot only after the backend passes.

## Dedicated Claw client VM

The persistent Claw agent and its project/session storage run in a separate
GPU-less sandbox VM on the primary server. This does not change the Gemma
launcher or consume model VRAM. The VM reaches only the primary server's
loopback model endpoint through a restricted SSH local forward; the API remains
non-public.

Keep the Claw bridge concurrency at two so it matches the two server slots.
Keep automatic Claw compaction at 110000 input tokens for the measured 163840-
token slot. The Claw completion ceiling is 32000 tokens, matching the current
default Opus budget; short responses still stop naturally. The deployed client
VM is limited to 8 vCPU and 16 GiB RAM; the
rejected 32 GiB client profile would leave insufficient headroom on the current
62 GiB hypervisor. The smaller secondary GPU server is not a suitable Claw VM
host.

The client VM has no model weights or GPU passthrough. Its unrestricted Claw
profile exposes the complete tool registry, public and private egress, and
operator-supplied credentials inherited from root-owned environment files.
Detailed migration, service templates,
rollback, and reboot/parallel/OCR evidence live in
[`FrankRappo/claw-code-parity`](https://github.com/FrankRappo/claw-code-parity/blob/main/integrations/telegram/DEDICATED-SANDBOX-VM.md).

Rollback in reverse order. Preserve the previous unit files, environment files,
runtime directory, and known-good model paths until the new profile completes
load testing.
