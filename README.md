# Gemma 4 AMD Vulkan operations

Reproducible operational configuration for a multimodal Gemma 4 31B deployment
using llama.cpp Vulkan across two AMD GPUs, plus a dependency-free Telegram
Vision bot.

## Included

- two-node Vulkan/RPC launchers and systemd units;
- adaptive Gemma 4 Vision at 280–1120 image tokens;
- RAM prompt cache disabled (`--cache-ram 0`);
- Q4 KV cache and configurable context/parallel slots;
- deterministic benchmark and configuration regression tests;
- Telegram text, PNG and JPEG screenshot support;
- capacity and rollback runbooks under `docs/`.

Claw Code project sessions and their Telegram bridge are maintained separately
in [`FrankRappo/claw-code-parity`](https://github.com/FrankRappo/claw-code-parity).
The two services communicate through an authenticated localhost-only bridge.

## Quick verification

```bash
python3 -m unittest discover -s llm_ops/systemd/tests -v
python3 -m unittest discover -s llm_ops/telegram_bot/tests -v
python3 llm_ops/systemd/verify-systemd-units.py
```

## Safety

This public repository intentionally contains no credentials, production IP
addresses, private data, or model weights. Review `SECURITY.md` before deployment.
