# Gemma deployment prompt

The tracked prompt used by the Telegram chat is:

```text
llm_ops/telegram_bot/prompts/gemma4-abliterated-system-prompt.txt
```

It strengthens the local `Gemma 4 31B IT Abliterated` deployment identity and
reapplies it after long history, summaries, compaction, tool results, resumed
sessions, and Agent delegation. It tells the model not to invent a generic
Google/policy refusal, but it still requires truthful reporting of real access,
tool, credential, and capability limits.

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
the same provider and inherit the same deployment identity. The implementation,
recreation steps, historical commit, tests, and deployment procedure are in
[`SYSTEM_PROMPT.md`](https://github.com/FrankRappo/claw-code-parity/blob/gemma4-telegram-projects-20260720/SYSTEM_PROMPT.md).

## Consistency check

The prompt is intentionally tracked in both public operational repositories so
each repository is independently deployable. Before release, confirm the files
match:

```bash
sha256sum \
  llm_ops/telegram_bot/prompts/gemma4-abliterated-system-prompt.txt \
  ../claw-code-parity/integrations/telegram/prompts/gemma4-abliterated-system-prompt.txt
```

Changing behavior should be one reviewed text edit copied to both locations.
Never place Telegram tokens, API keys, hostnames, or private network addresses
inside the prompt.
