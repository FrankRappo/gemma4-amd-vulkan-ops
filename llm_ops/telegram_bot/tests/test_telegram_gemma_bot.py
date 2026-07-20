import io
import unittest
from unittest import mock

from llm_ops.telegram_bot import telegram_gemma_bot as bot


PNG = b"\x89PNG\r\n\x1a\n" + b"test-png"
JPEG = b"\xff\xd8\xff" + b"test-jpeg"


class FakeResponse:
    def __init__(self, data, content_length=None):
        self._stream = io.BytesIO(data)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size=-1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class ImageSelectionTests(unittest.TestCase):
    def test_selects_largest_photo_variant(self):
        attachment = bot.select_image_attachment({
            "photo": [
                {"file_id": "small", "file_size": 10},
                {"file_id": "large", "file_size": 30},
                {"file_id": "medium", "file_size": 20},
            ]
        })
        self.assertEqual(attachment["file_id"], "large")
        self.assertEqual(attachment["declared_mime_type"], "image/jpeg")

    def test_rejects_non_image_document(self):
        with self.assertRaisesRegex(bot.ImageInputError, "PNG и JPEG"):
            bot.select_image_attachment({
                "document": {
                    "file_id": "pdf",
                    "mime_type": "application/pdf",
                    "file_size": 10,
                }
            })

    def test_rejects_declared_oversize_attachment(self):
        with mock.patch.object(bot, "MAX_IMAGE_BYTES", 8):
            with self.assertRaisesRegex(bot.ImageInputError, "слишком большое"):
                bot.select_image_attachment({
                    "document": {
                        "file_id": "large",
                        "mime_type": "image/png",
                        "file_size": 9,
                    }
                })


class ImageDownloadTests(unittest.TestCase):
    def test_content_length_limit_is_enforced_before_read(self):
        response = FakeResponse(b"", content_length=5)
        with mock.patch.object(
            bot.urllib.request,
            "urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(bot.ImageInputError, "слишком большое"):
                bot._download_limited("https://example.invalid/image", max_bytes=4)

    def test_stream_limit_applies_without_content_length(self):
        with mock.patch.object(
            bot.urllib.request,
            "urlopen",
            return_value=FakeResponse(b"12345"),
        ):
            with self.assertRaisesRegex(bot.ImageInputError, "слишком большое"):
                bot._download_limited("https://example.invalid/image", max_bytes=4)

    def test_download_validates_signature_and_returns_actual_type(self):
        attachment = {
            "file_id": "telegram-file",
            "declared_mime_type": "image/png",
            "kind": "document",
        }
        with mock.patch.object(
            bot,
            "tg",
            return_value={"result": {"file_path": "documents/screenshot.png"}},
        ), mock.patch.object(bot, "_download_limited", return_value=PNG):
            data, mime_type = bot.download_telegram_image(attachment)
        self.assertEqual(data, PNG)
        self.assertEqual(mime_type, "image/png")

    def test_rejects_declared_and_actual_type_mismatch(self):
        attachment = {
            "file_id": "telegram-file",
            "declared_mime_type": "image/png",
            "kind": "document",
        }
        with mock.patch.object(
            bot,
            "tg",
            return_value={"result": {"file_path": "documents/screenshot.png"}},
        ), mock.patch.object(bot, "_download_limited", return_value=JPEG):
            with self.assertRaisesRegex(bot.ImageInputError, "не совпадает"):
                bot.download_telegram_image(attachment)


class LlmPayloadTests(unittest.TestCase):
    def setUp(self):
        bot.HISTORY.clear()

    def test_multimodal_payload_places_image_first_and_does_not_store_base64(self):
        captured = {}

        def fake_http_json(url, payload=None, timeout=None):
            captured["url"] = url
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "На скриншоте код 42."}}]}

        with mock.patch.object(bot, "http_json", side_effect=fake_http_json):
            answer = bot.llm_answer(
                100,
                "Какой код?",
                image=PNG,
                image_mime_type="image/png",
            )

        self.assertEqual(answer, "На скриншоте код 42.")
        content = captured["payload"]["messages"][-1]["content"]
        self.assertEqual([part["type"] for part in content], ["image_url", "text"])
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(content[1]["text"], "Какой код?")
        self.assertIsInstance(bot.HISTORY[100][0]["content"], str)
        self.assertNotIn("base64", bot.HISTORY[100][0]["content"])

    def test_text_payload_remains_plain_string(self):
        captured = {}

        def fake_http_json(url, payload=None, timeout=None):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "Ответ"}}]}

        with mock.patch.object(bot, "http_json", side_effect=fake_http_json):
            bot.llm_answer(101, "Обычный вопрос")
        self.assertEqual(
            captured["payload"]["messages"][-1]["content"],
            "Обычный вопрос",
        )
        self.assertEqual(captured["payload"]["top_p"], bot.TOP_P)
        self.assertEqual(captured["payload"]["top_k"], bot.TOP_K)
        self.assertEqual(
            captured["payload"]["chat_template_kwargs"]["enable_thinking"],
            bot.ENABLE_THINKING,
        )


class ExistingBotBehaviorTests(unittest.TestCase):
    def setUp(self):
        bot.HISTORY.clear()
        bot.TOKEN_LIMITS.clear()

    def test_username_allowlist_is_preserved(self):
        with mock.patch.object(bot, "ALLOWED", set()), mock.patch.object(
            bot,
            "ALLOWED_USERNAMES",
            {"owner"},
        ):
            self.assertTrue(bot.allowed_user({"id": 100, "username": "@Owner"}))
            self.assertFalse(bot.allowed_user({"id": 101, "username": "guest"}))

    def test_tokens_command_updates_only_that_chat(self):
        message = {
            "chat": {"id": 10},
            "from": {"id": 20},
            "message_id": 30,
            "text": "/tokens 768",
        }
        with mock.patch.object(bot, "ALLOWED", set()), mock.patch.object(
            bot,
            "ALLOWED_USERNAMES",
            set(),
        ), mock.patch.object(bot, "send_message") as send:
            bot.handle_message(message)
        self.assertEqual(bot.chat_token_limit(10), 768)
        self.assertEqual(bot.chat_token_limit(11), bot.MAX_TOKENS)
        self.assertIn("768", send.call_args.args[1])

    def test_help_advertises_screenshot_support(self):
        message = {
            "chat": {"id": 10},
            "from": {"id": 20},
            "message_id": 30,
            "text": "/help",
        }
        with mock.patch.object(bot, "ALLOWED", set()), mock.patch.object(
            bot,
            "ALLOWED_USERNAMES",
            set(),
        ), mock.patch.object(bot, "send_message") as send:
            bot.handle_message(message)
        self.assertIn("PNG/JPEG", send.call_args.args[1])


class MessageHandlingTests(unittest.TestCase):
    def setUp(self):
        bot.HISTORY.clear()

    def test_photo_without_caption_uses_default_prompt(self):
        message = {
            "chat": {"id": 1},
            "from": {"id": 2},
            "message_id": 3,
            "photo": [{"file_id": "photo", "file_size": len(JPEG)}],
        }
        with mock.patch.object(bot, "ALLOWED", set()), mock.patch.object(
            bot,
            "send_typing",
        ), mock.patch.object(
            bot,
            "download_telegram_image",
            return_value=(JPEG, "image/jpeg"),
        ) as download, mock.patch.object(
            bot,
            "llm_answer",
            return_value="Описание",
        ) as answer, mock.patch.object(bot, "send_message") as send:
            bot.handle_message(message)

        download.assert_called_once()
        answer.assert_called_once_with(
            1,
            "",
            image=JPEG,
            image_mime_type="image/jpeg",
        )
        send.assert_called_once_with(1, "Описание", reply_to=3)

    def test_unauthorized_image_is_not_downloaded(self):
        message = {
            "chat": {"id": 1},
            "from": {"id": 99},
            "message_id": 3,
            "photo": [{"file_id": "photo", "file_size": len(JPEG)}],
        }
        with mock.patch.object(bot, "ALLOWED", {2}), mock.patch.object(
            bot,
            "download_telegram_image",
        ) as download, mock.patch.object(bot, "send_message"):
            bot.handle_message(message)
        download.assert_not_called()

    def test_unsupported_document_gets_safe_validation_message(self):
        message = {
            "chat": {"id": 1},
            "from": {"id": 2},
            "message_id": 3,
            "document": {
                "file_id": "pdf",
                "file_size": 50,
                "mime_type": "application/pdf",
            },
        }
        with mock.patch.object(bot, "ALLOWED", set()), mock.patch.object(
            bot,
            "download_telegram_image",
        ) as download, mock.patch.object(bot, "send_message") as send:
            bot.handle_message(message)
        download.assert_not_called()
        self.assertIn("PNG и JPEG", send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
