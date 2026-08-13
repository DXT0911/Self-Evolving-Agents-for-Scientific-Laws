import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from .llm import DeepSeekLLM, LLMConfig


class DeepSeekThinkingConfigTests(unittest.TestCase):
    def test_chat_request_can_disable_provider_reasoning(self) -> None:
        config = LLMConfig(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="test",
            max_tokens=6000,
            thinking=False,
        )
        llm = object.__new__(DeepSeekLLM)
        llm.config = config
        create = Mock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="done", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
                model="deepseek-v4-pro",
                id="response",
            )
        )
        llm.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        response = llm._call_chat([{"role": "user", "content": "work"}])

        self.assertEqual(response.content, "done")
        request = create.call_args.kwargs
        self.assertEqual(request["max_tokens"], 6000)
        self.assertEqual(
            request["extra_body"],
            {
                "chat_template_kwargs": {"thinking": False},
                "separate_reasoning": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
