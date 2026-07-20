# Gemma 4 srv1/srv2 systemd deployment

These files define the reversible two-host deployment:

- `srv1`: one multimodal `llama-server` on `127.0.0.1:8080`;
- `srv2`: one Vulkan RPC worker on the private `10.30.0.0/24` link;
- model layers are split equally between `Vulkan0` and `RPC0`;
- the default profile is 32K context, one slot and Q4 KV cache;
- Gemma 4 Vision uses a `280–1120` visual-token range for high-detail OCR;
- logical, physical and mtmd image batch limits default to `1280`, so the full
  1120-token non-causal image chunk fits without splitting;
- host-memory prompt caching remains disabled (`--cache-ram 0`);
- MTP is present as an opt-in benchmark flag and is disabled by default.

The 32K/one-slot default remains intentional after a 2026-07-20 capacity probe.
`CTX_SIZE=524288`, `PARALLEL=2` successfully created two 256K slots, but left
only 75.5 MiB free VRAM on srv1 and was rolled back before Vision/load testing.
Do not deploy that maximum profile. The next staged candidates are 192K, 160K
and 128K per slot, documented in
[`../../docs/context-parallel-capacity.md`](../../docs/context-parallel-capacity.md).

The high-detail profile follows Google's documented `max_soft_tokens=1120`
option. It does not replace the model or projector. To roll back to the previous
280-token image profile, set all three batch limits to `512` and set
`VISION_MIN_TOKENS=VISION_MAX_TOKENS=280` in the environment file, then restart
only `llm-gemma4-primary.service`.

The profile was deployed on 2026-07-20 after a same-fixture A/B. It corrected a
small OCR date (`07-29` to the expected `07-20`) while dense-image latency rose
from 20.33 s to 30.54 s. The measured cgroup delta during OCR was +501.9 MiB;
swap did not grow, the service startup peak remained about 1.25 GiB, and the
host retained 35.77 GiB `MemAvailable`. The full research, measurements,
production evidence and rollback are recorded in
[`../../docs/vision-1120.md`](../../docs/vision-1120.md).

`llm-stability-setup.service` is the canonical boot-order definition shared by
both hosts. It must remain ordered after `network-online.target`, but it must
never declare `After=multi-user.target`: the unit is itself wanted by
`multi-user.target`, so that dependency creates a cycle and can make systemd
drop the Gemma/RPC start job during boot.

The runtime and model paths are pinned in the launchers. Do not mix an RPC
worker and a server from different llama.cpp builds. Keep RPC bound to the
private point-to-point link: upstream describes the protocol as unauthenticated
and not suitable for an untrusted network.

Deployment order is `srv2 RPC -> srv1 primary`. Rollback order is the reverse,
followed by starting the preserved `llm-gpu2-local-server.service` on `srv2`.
The exact deployment, validation and rollback commands are recorded in the
project runbook rather than duplicated here.

Before deploying any edited unit, run the dependency regression check:

```bash
python3 verify-systemd-units.py
```

On each target host, also validate the installed graph after `daemon-reload`:

```bash
systemctl daemon-reload
systemd-analyze verify \
  /etc/systemd/system/llm-stability-setup.service \
  /etc/systemd/system/llm-gpu2-rpc-worker.service   # srv2
```

Use `llm-gemma4-primary.service` instead of the RPC unit for the corresponding
check on `srv1`.
