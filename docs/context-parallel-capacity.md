# Context and parallel-slot capacity

## Proven maximum allocation is not a safe production profile

A two-slot startup with `CTX_SIZE=524288` succeeded and exposed two 262144-token
slots, matching Gemma 4's native 256K context. It left only about 75.5 MiB free
VRAM on the primary GPU (roughly 0.46%). The profile was rolled back before
Vision or concurrent load testing.

Such a small reserve is unsafe: image embeddings, temporary compute buffers,
driver allocations, concurrent decoding, and allocator fragmentation can cause
an out-of-memory error or terminate the service even though startup succeeds.

## Production decision (measured 2026-07-20)

The selected profile is:

```dotenv
CTX_SIZE=327680
PARALLEL=2
```

llama.cpp divides the total context between the two slots, producing **two
independent 163840-token (160 Ki token) slots**. RAM prompt caching remains
disabled (`--cache-ram 0`). The selected profile survived text, dense Vision,
concurrent mixed load, and a prompt beyond the former 32K limit without a
service restart or cgroup memory event.

| Check | Result |
|---|---:|
| Idle free VRAM | 1.689 GiB |
| Minimum free VRAM, concurrent 128-token text | 1.677 GiB |
| Minimum free VRAM, dense Vision | 1.218 GiB |
| Minimum free VRAM, 36046-token long prompt | 1.207 GiB |
| Service restarts | 0 |
| cgroup `oom` / `oom_kill` | 0 / 0 |
| Single-request generation | 11.738 token/s |
| Two-request aggregate generation | 19.272 token/s |
| Aggregate gain versus 32K/one-slot baseline | 71.98% |

The throughput gain applies when requests overlap. It is **not** a 72% speedup
for one conversation: each stream measured about 8–12% slower under concurrent
decoding, while the server completed much more total work per second.

The 192 Ki-token-per-slot candidate (`CTX_SIZE=393216`, `PARALLEL=2`) was
rejected before heavy load: only 929 MiB free VRAM remained at idle, already
below the 1 GiB guard. The native 256 Ki-token-per-slot allocation was also
rejected because it left only about 75.5 MiB free.

The complete sanitized measurement record is in
[`results/context-parallel-20260720.json`](results/context-parallel-20260720.json).

## Candidate ladder

Test one candidate at a time, always with two simultaneous requests and a Vision
fixture:

| Total `CTX_SIZE` | `PARALLEL` | Context per slot |
|---:|---:|---:|
| 393216 | 2 | 196608 (192 Ki tokens) — rejected |
| 327680 | 2 | 163840 (160 Ki tokens) — selected |
| 262144 | 2 | 131072 (128 Ki tokens) |
| 196608 | 2 | 98304 (96 Ki tokens) |

Do not promote a candidate solely because the service starts. Require stable
VRAM reserve, no restarts, successful long-context text, successful 1120-token
Vision, two concurrent requests, and acceptable throughput.

Claw automatic compaction must be below the effective per-slot window. The
deployed threshold is **110000 input tokens**, 67.1% of a 163840-token slot.
That leaves 53840 tokens for the system prompt, tool results, image tokens,
continued turns, and output. Compaction summarizes completed history and keeps
the project/session mapping; it does not silently expand the model's native
window.

## Why the VRAM reserve matters

An idle allocation is not the peak allocation. Vision embeddings, Vulkan
scratch buffers, simultaneous decode, driver bookkeeping, and allocator
fragmentation consume additional memory after startup. Exhausting VRAM may
abort a request, reset the Vulkan device, kill `llama-server`, or make systemd
restart it, losing in-flight work. The selected profile's observed minimum is
about 1.20 GiB, not a universal guarantee; repeat the fixtures after any model,
runtime, batch, KV-cache, or GPU-driver change.
