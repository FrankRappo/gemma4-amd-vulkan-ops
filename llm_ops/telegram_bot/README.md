# Telegram bot multimodal source

This directory is the tracked deployment source for the dependency-free Telegram
bridge running on the jump host. It reaches the srv1 `llama-server` through the
jump-local `http://127.0.0.1:18080` tunnel.

Long Gemma answers are sent losslessly as ordered Telegram chunks of at most
3900 characters. The default output budget is 4096 tokens and `/tokens` may
raise one chat to 8192; this changes model generation length, not the Telegram
chunk size.

## Supported input

- text messages;
- Telegram photos (the largest JPEG variant is selected);
- PNG or JPEG images sent as documents, including screenshots;
- an optional photo/document caption becomes the image question; without a
  caption the bot asks the model to describe the image and extract its text.

The image is validated by declared size, downloaded with a hard streaming limit,
checked by its file signature, encoded as an OpenAI-compatible `image_url` data
URI, and sent before the text content. Images and base64 payloads are never stored
in chat history or on disk.

## Configuration and safety

Keep the production environment outside the checkout (for example under
`/etc/default/`). It must not be copied to Git. `MAX_IMAGE_BYTES` is optional and defaults to 10 MiB. Only JPEG and
PNG are accepted.

Multimodal requests require a llama-server started with a compatible Gemma 4
multimodal projector (`mmproj`). The live backend and the deployed bot path both
passed image smoke tests before the bot was declared active.

Deployment and rollback guidance is in [`../../docs/telegram-vision-bot.md`](../../docs/telegram-vision-bot.md).

## Test

From the repository root:

```bash
python3 -m unittest discover -s llm_ops/telegram_bot/tests -v
```

The tests mock Telegram and llama-server; they do not use a token, the network,
or remote services.
