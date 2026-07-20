# Telegram Vision bot deployment

The bot is dependency-free Python and talks to an OpenAI-compatible local
endpoint. Keep the Telegram token and user allowlist in an external environment
file.

Required environment:

```ini
TELEGRAM_BOT_TOKEN=replace-me
BOT_ALLOWED_USER_IDS=123456789
LLM_BASE_URL=http://127.0.0.1:18080
SYSTEM_PROMPT_FILE=/opt/tg-gemma-bot/gemma4-abliterated-system-prompt.txt
MAX_TOKENS=4096
MAX_RESPONSE_TOKENS=8192
MAX_IMAGE_BYTES=10485760
```

`SYSTEM_PROMPT_FILE` points to the tracked, strengthened deployment prompt. It
is hot-reloaded for every model request; see [`system-prompt.md`](./system-prompt.md).

The bot validates declared and streamed size, verifies PNG/JPEG signatures, and
does not retain base64 image payloads in conversation history. Bind the model
endpoint locally and reach it through a separately managed SSH tunnel when the
bot and model run on different trusted hosts.

Telegram permits only a bounded amount of text in one message. The bot keeps
every character returned by Gemma and sends it as ordered chunks of at most
3900 characters, preferring paragraph, newline, and word boundaries. Only the
first chunk replies to the user message and only the last repeats the keyboard.
The default generation budget is 4096 tokens; `/tokens` can select up to 8192
for a chat. The token budget limits model generation, while chunking prevents
Telegram from truncating the generated text.

Validate with mocked unit tests before deployment, then run text, PNG, JPEG,
unauthorized-user, oversized-file, service-restart, and rollback smoke tests.
The long-output regression reconstructs the complete original text from all
mocked `sendMessage` payloads and verifies the 3900-character bound.
