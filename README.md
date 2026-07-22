# Gemma 4 AMD Vulkan operations

Reproducible operational configuration for a multimodal Gemma 4 31B deployment
using llama.cpp Vulkan across two AMD GPUs, plus a dependency-free Telegram
Vision bot.

## Included

- two-node Vulkan/RPC launchers and systemd units;
- adaptive Gemma 4 Vision at 280–1120 image tokens;
- RAM prompt cache disabled (`--cache-ram 0`);
- Q4 KV cache and a measured two-slot 160K-context production profile;
- deterministic benchmark and configuration regression tests;
- Telegram text, PNG and JPEG screenshot support;
- capacity and rollback runbooks under `docs/`.
- isolated Mesa/RADV and llama.cpp Vulkan candidate build/deploy tooling.
- opt-in, parameterized MTP and ngram profiles that remain disabled by default.

Claw Code project sessions and their Telegram bridge are maintained separately
in [`FrankRappo/claw-code-parity`](https://github.com/FrankRappo/claw-code-parity).
The agent now runs in a dedicated 8-vCPU/16-GiB sandbox VM and reaches Gemma
through a restricted SSH tunnel to the model host's loopback API. The Telegram
side reaches the agent through a separately authenticated localhost-only
reverse bridge. See [`docs/deployment.md`](docs/deployment.md).

## Verified capacity profile

The current launcher defaults to `CTX_SIZE=327680`, `PARALLEL=2`: two 163840
token slots. The measured minimum free VRAM was 1.20 GiB, and two simultaneous
requests delivered 19.272 token/s aggregate (+71.98% over the former one-slot
baseline). RAM prompt caching remains off. See
[`docs/context-parallel-capacity.md`](docs/context-parallel-capacity.md) for the
fixtures, rejected larger profiles, safety reasoning, and compaction boundary.

## Quick verification

```bash
python3 -m unittest discover -s llm_ops/systemd/tests -v
python3 -m unittest discover -s llm_ops/telegram_bot/tests -v
python3 llm_ops/systemd/verify-systemd-units.py
```

## Safety

This public repository intentionally contains no credentials, production IP
addresses, private data, or model weights. Review `SECURITY.md` before deployment.

Deployment prompt behavior is documented in [`docs/system-prompt.md`](docs/system-prompt.md).

GFX1200 driver capability work, CUDA-to-Vulkan candidate provenance,
deterministic A/B gates and rollback are documented in
[`docs/vulkan-rdna4-performance.md`](docs/vulkan-rdna4-performance.md).
