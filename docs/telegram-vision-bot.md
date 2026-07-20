# Telegram Vision bot deployment

The bot is dependency-free Python and talks to an OpenAI-compatible local
endpoint. Keep the Telegram token and user allowlist in an external environment
file.

Required environment:

```ini
TELEGRAM_BOT_TOKEN=replace-me
BOT_ALLOWED_USER_IDS=123456789
LLM_BASE_URL=http://127.0.0.1:18080
MAX_TOKENS=512
MAX_IMAGE_BYTES=10485760
```

The bot validates declared and streamed size, verifies PNG/JPEG signatures, and
does not retain base64 image payloads in conversation history. Bind the model
endpoint locally and reach it through a separately managed SSH tunnel when the
bot and model run on different trusted hosts.

Validate with mocked unit tests before deployment, then run text, PNG, JPEG,
unauthorized-user, oversized-file, service-restart, and rollback smoke tests.
