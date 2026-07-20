# Deployment sequence

1. Install matching llama.cpp Vulkan runtime builds on both GPU nodes.
2. Bind the RPC worker only to a trusted private network.
3. Start the remote RPC worker and verify its port locally.
4. Start the primary multimodal server bound to localhost.
5. Verify `/health`, `/props`, slot count, effective context, and GPU memory.
6. Run deterministic text and Vision fixtures.
7. Start the Telegram tunnel and bot only after the backend passes.

Rollback in reverse order. Preserve the previous unit files, environment files,
runtime directory, and known-good model paths until the new profile completes
load testing.
