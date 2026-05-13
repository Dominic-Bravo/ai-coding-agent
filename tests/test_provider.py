import os
import unittest
from unittest.mock import MagicMock, patch

from llm.provider import GeminiProvider


class TestGetRoleInstructions(unittest.TestCase):
    def setUp(self):
        self.p = GeminiProvider.__new__(GeminiProvider)

    def test_architect(self):
        text = GeminiProvider.get_role_instructions(self.p, "architect")
        self.assertIn("Architect Agent", text)

    def test_engineer_aliases(self):
        a = GeminiProvider.get_role_instructions(self.p, "engineer")
        b = GeminiProvider.get_role_instructions(self.p, "lead engineer")
        c = GeminiProvider.get_role_instructions(self.p, "Lead Engineer")
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertIn("Lead Engineer", a)

    def test_unknown_defaults_to_dom(self):
        dom = GeminiProvider.get_role_instructions(self.p, "dom")
        other = GeminiProvider.get_role_instructions(self.p, "not-a-real-role")
        self.assertEqual(dom, other)


class TestAsk(unittest.TestCase):
    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("llm.provider.OpenAI")
    def test_ask_returns_message_and_sends_engineer_system_prompt(
        self, mock_openai_cls: MagicMock
    ):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="model reply"))]
        )

        provider = GeminiProvider()
        out = provider.ask("engineer", "Implement X")

        self.assertEqual(out, "model reply")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], provider.model)
        messages = kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Lead Engineer", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "Implement X")


if __name__ == "__main__":
    unittest.main()
