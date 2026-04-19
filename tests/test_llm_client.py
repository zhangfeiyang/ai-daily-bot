# tests/test_llm_client.py
from unittest.mock import patch, MagicMock
from src.llm.client import LLMClient


def test_llm_client_uses_default_provider():
    config = {
        "default": "openai",
        "providers": {
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        },
    }
    client = LLMClient(config)
    assert client.provider == "openai"
    assert client.model == "gpt-4o"


def test_llm_client_generate_openai():
    config = {
        "default": "openai",
        "providers": {
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        },
    }
    client = LLMClient(config)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Generated article content"

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = mock_response

        result = client.generate("system prompt", "user prompt")
        assert result == "Generated article content"


def test_llm_client_anthropic_generate():
    config = {
        "default": "anthropic",
        "providers": {
            "anthropic": {
                "api_key": "sk-ant-test",
                "base_url": "https://api.anthropic.com",
                "model": "claude-sonnet-4-6-20250514",
            }
        },
    }
    client = LLMClient(config)

    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Claude generated content"

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_anthropic = MagicMock()
        mock_anthropic_cls.return_value = mock_anthropic
        mock_anthropic.messages.create.return_value = mock_response

        result = client.generate("system prompt", "user prompt")
        assert result == "Claude generated content"
