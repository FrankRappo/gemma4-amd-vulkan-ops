# Imported Gemma / AMD Vulkan operations documentation

Project:

```text
/work/claster/gemma4-amd-vulkan-ops
```

This directory contains exact project-local copies of the GPU/Gemma/ClawCod
operations documentation that previously existed only at the root of:

```text
/work/claster/analise_storage
```

The originals remain unchanged. No service, model, GPU process, unit file,
configuration, source code or Git index was modified.

## Integrity

- Imported Markdown documents: **12**
- Exact source/copy matches at creation: **12/12**
- `SOURCE-MANIFEST.tsv` records source path, project copy and SHA-256.
- `SHA256SUMS` verifies every imported Markdown document.

Verify:

```bash
cd /work/claster/gemma4-amd-vulkan-ops/docs/imported-from-analise-storage
sha256sum -c SHA256SUMS
```

## Scope

The archive includes:

- AMD Vulkan upgrade and two-GPU setup;
- high-resolution vision configuration;
- ClawCod/Gemma compatibility and context-parallel probes;
- infrastructure separation;
- GPU monitoring and context tuning;
- Telegram vision bot;
- VM120/Claw/Gemma storage setup;
- srv2 handoff and storage-analysis plan.

The repository's existing operational documentation remains canonical in
`README.md`, `SECURITY.md`, `docs/`, `llm_ops/` and `patches/`.

At copy time no local process was visible as an active ClawCod/Gemma GPU
consumer, so the target was selected from the actual repository purpose rather
than from a live PID.

## Git rule

These files are owner-requested documentation. They were not staged or
committed. If committed later, use an explicit documentation allowlist; never
use `git add -A`.
