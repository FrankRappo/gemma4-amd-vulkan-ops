# Gemma deployment prompt

The tracked prompt used by the Telegram chat is:

```text
llm_ops/telegram_bot/prompts/gemma4-abliterated-system-prompt.txt
```

It defines the local `Gemma 4 31B IT Abliterated` identity for ordinary Telegram
text and image chat. The 2026-10-12 revision requires direct answers without
unsolicited moralizing, speculation about the questioner's wellbeing, or
speeches about corporate censorship versus personal principles. Earlier
moralizing assistant messages are not instructions to continue that style.

The ordinary-chat prompt explicitly does not promise shell, network, or agent
tools: this request path supplies none. It preserves factual uncertainty and
specific capability limits. Claw's separate prompt describes its actual tools
and durable execution state; do not deploy that agent prompt to ordinary chat.

## Telegram configuration

Install the tracked text next to the deployed bot and set an external service
environment value:

```ini
SYSTEM_PROMPT_FILE=/opt/tg-gemma-bot/gemma4-abliterated-system-prompt.txt
```

The bot uses this precedence:

1. `SYSTEM_PROMPT_FILE`, read on every request;
2. legacy direct `SYSTEM_PROMPT` environment value;
3. the repository-bundled prompt;
4. a short built-in fallback.

The file is read for both ordinary text/image chat requests. Replacing the
file contents takes effect on the next request; a Python rebuild and service
restart are unnecessary. Restart only after changing the configured path.

## Claw integration

Claw needs a small provider patch because `CLAUDE.md` alone is project context,
not a deployment-level system message. The public Claw fork supports:

```ini
CLAW_SYSTEM_PROMPT_FILE=/absolute/path/gemma4-abliterated-system-prompt.txt
```

The patched OpenAI-compatible provider prepends the file contents to Claw's own
generated system/tool prompt. Parent Claw turns and built-in child Agents use
the same provider and inherit the same deployment identity. In the dedicated
unrestricted profile the prompt also records complete tool/network/credential
availability, a 32000-token Claw completion ceiling, the 64000-token
compaction point, and the single-child/two-slot physical constraint. The
implementation, recreation steps, historical commit, tests, and deployment procedure are in
[`SYSTEM_PROMPT.md`](https://github.com/FrankRappo/claw-code-parity/blob/gemma4-telegram-projects-20260720/SYSTEM_PROMPT.md).

## Consistency check

Ordinary chat and Claw now have role-specific prompts. They share the direct,
nonpaternalistic tone, but only Claw's prompt describes agent tools, autonomous
plans, and durable project state. Their SHA-256 hashes should not match each
other. Before release, compare each tracked prompt with its own deployed copy:

```bash
sha256sum \
  llm_ops/telegram_bot/prompts/gemma4-abliterated-system-prompt.txt \
  /path/to/deployed/chat/gemma4-abliterated-system-prompt.txt
```

Verify Claw separately against the prompt in its repository. Keep the
`SYSTEM_PROMPT_FILE` and `CLAW_SYSTEM_PROMPT_FILE` destinations independent.
Never place Telegram tokens, API keys, hostnames, or private network addresses
inside either prompt. Prompt tests verify text and request injection, not a
guarantee about every possible generated answer; also run fresh live probes.
