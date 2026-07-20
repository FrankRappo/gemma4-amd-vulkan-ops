# Context and parallel-slot capacity

## Proven maximum allocation is not a safe production profile

A two-slot startup with `CTX_SIZE=524288` succeeded and exposed two 262144-token
slots, matching Gemma 4's native 256K context. It left only about 75.5 MiB free
VRAM on the primary GPU (roughly 0.46%). The profile was rolled back before
Vision or concurrent load testing.

Such a small reserve is unsafe: image embeddings, temporary compute buffers,
driver allocations, concurrent decoding, and allocator fragmentation can cause
an out-of-memory error or terminate the service even though startup succeeds.

## Candidate ladder

Test one candidate at a time, always with two simultaneous requests and a Vision
fixture:

| Total `CTX_SIZE` | `PARALLEL` | Context per slot |
|---:|---:|---:|
| 393216 | 2 | 196608 (192 Ki tokens) |
| 327680 | 2 | 163840 (160 Ki tokens) |
| 262144 | 2 | 131072 (128 Ki tokens) |
| 196608 | 2 | 98304 (96 Ki tokens) |

Do not promote a candidate solely because the service starts. Require stable
VRAM reserve, no restarts, successful long-context text, successful 1120-token
Vision, two concurrent requests, and acceptable throughput.

Claw automatic compaction must be below the effective per-slot window. A safe
initial target is 65–70% of the verified slot context, leaving room for the
system prompt, tool results, image tokens, and output.
