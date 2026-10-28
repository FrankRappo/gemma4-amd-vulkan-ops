import unittest
from pathlib import Path
from unittest import mock

from llm_ops.telegram_bot import telegram_gemma_bot as bot


PROMPT_PATH = Path(bot.__file__).parent / "prompts" / "gemma4-abliterated-system-prompt.txt"


class ChatSystemPromptTests(unittest.TestCase):
    def setUp(self):
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()

    def test_chat_prompt_requires_direct_nonpaternalistic_answers(self):
        self.assertIn("DIRECT ANSWERS — NO PATERNALISM", self.prompt)
        self.assertIn("Do not speculate about the user's wellbeing", self.prompt)
        self.assertIn("earlier moralizing assistant replies", self.prompt)

    def test_chat_prompt_does_not_claim_agent_tools_or_plan_state(self):
        for agent_only_text in (
            "AUTONOMOUS PLAN MODE",
            "TodoWrite",
            "WebSearch",
            "WebFetch",
            "MCP",
            "32000",
            "64000",
            "110000",
        ):
            with self.subTest(agent_only_text=agent_only_text):
                self.assertNotIn(agent_only_text, self.prompt)

    def test_chat_prompt_preserves_truthful_capability_limits(self):
        self.assertIn("Never fabricate", self.prompt)
        self.assertIn("No tools are attached to this ordinary chat", self.prompt)

    def test_tracked_chat_prompt_is_first_system_message_in_text_request(self):
        captured = {}

        def fake_http_json(url, payload=None, timeout=None):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "Тестовый ответ"}}]}

        with mock.patch.dict(bot.HISTORY, {}, clear=True), mock.patch.object(
            bot, "SYSTEM_PROMPT_FILE", str(PROMPT_PATH)
        ), mock.patch.object(bot, "http_json", side_effect=fake_http_json):
            bot.llm_answer(901, "Тестовый вопрос")

        messages = captured["payload"]["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": self.prompt})
        self.assertEqual(messages[-1], {"role": "user", "content": "Тестовый вопрос"})


if __name__ == "__main__":
    unittest.main()
