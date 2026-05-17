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
            },
            "minimax": {
                "api_key": "sk-minimax",
                "base_url": "https://api.minimaxi.com/v1",
                "model": "MiniMax-M2.7",
                "protocol": "openai",
            }
        },
    }
    client = LLMClient(config)

    # Mock streaming response
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Generated article content"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = None

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = iter([mock_chunk1, mock_chunk2])

        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "Generated article content"
        mock_openai.chat.completions.create.return_value = response

        result = client.generate("system prompt", "user prompt")
        assert result == "Generated article content"
        assert mock_openai_cls.call_args.kwargs["base_url"] == "https://api.minimaxi.com/v1"
        assert mock_openai.chat.completions.create.call_args.kwargs["model"] == "MiniMax-M2.7"


def test_llm_client_generate_requires_minimax_config():
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

    try:
        client.generate("system prompt", "user prompt")
    except ValueError as e:
        assert "MiniMax-M2.7 provider config is required" in str(e)
    else:
        raise AssertionError("text generation should require minimax config")


def test_llm_client_ignores_non_minimax_default_for_text_generation():
    config = {
        "default": "custom",
        "providers": {
            "custom": {
                "api_key": "sk-custom",
                "base_url": "https://custom.example/v1",
                "model": "auto",
                "protocol": "openai",
            },
            "minimax": {
                "api_key": "sk-minimax",
                "base_url": "https://api.minimaxi.com/v1",
                "model": "MiniMax-M2.7",
                "protocol": "openai",
            },
        },
    }
    client = LLMClient(config)

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "MiniMax content"
    minimax_client = MagicMock()
    minimax_client.chat.completions.create.return_value = response

    def fake_openai(api_key=None, base_url=None, timeout=None):
        if base_url == "https://api.minimaxi.com/v1":
            return minimax_client
        raise AssertionError(f"unexpected base_url: {base_url}")

    with patch("openai.OpenAI", side_effect=fake_openai):
        result = client.generate("system prompt", "user prompt")

    assert result == "MiniMax content"
    assert minimax_client.chat.completions.create.called


def test_llm_client_strips_think_blocks():
    config = {
        "default": "openai",
        "providers": {
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            },
            "minimax": {
                "api_key": "sk-minimax",
                "base_url": "https://api.minimaxi.com/v1",
                "model": "MiniMax-M2.7",
                "protocol": "openai",
            }
        },
    }
    client = LLMClient(config)

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "<think>Let me reason</think>正文"

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = response

        result = client.generate("system prompt", "user prompt")

    assert result == "正文"


def test_generate_with_images_uses_minimax_mcp_protocol():
    config = {
        "default": "openai",
        "providers": {
            "vision": {
                "api_key": "sk-minimax",
                "api_host": "https://api.minimaxi.com",
                "model": "minimax-mcp-understand-image",
                "protocol": "minimax_mcp",
            }
        },
    }
    client = LLMClient(config)

    with patch("src.minimax_mcp.MiniMaxMCPClient.understand_image", return_value="YES"):
        result = client.generate_with_images("system", "text", ["https://example.com/a.png"])

    assert result == "1: YES"


def test_llm_client_generate_never_uses_opencli_provider():
    config = {
        "default": "gemini",
        "providers": {
            "gemini": {
                "protocol": "opencli",
                "site": "gemini",
                "timeout": 180,
                "new": True,
            },
            "minimax": {
                "api_key": "sk-minimax",
                "base_url": "https://api.minimaxi.com/v1",
                "model": "MiniMax-M2.7",
                "protocol": "openai",
            },
        },
    }
    client = LLMClient(config)

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "MiniMax generated content"

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = response
        result = client.generate("system prompt", "user prompt")

    assert result == "MiniMax generated content"


def test_generate_with_images_rejects_opencli_vision(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake")
    config = {
        "default": "gemini",
        "providers": {
            "vision": {
                "protocol": "opencli",
                "site": "deepseek",
                "model": "vision",
                "timeout": 180,
            }
        },
    }
    client = LLMClient(config)

    try:
        client.generate_with_images("system", "text", [str(image)])
    except ValueError as e:
        assert "OpenCLI browser providers are disabled for image understanding" in str(e)
    else:
        raise AssertionError("OpenCLI vision should be rejected")


def test_opencli_no_response_does_not_trigger_text_fallback():
    config = {
        "default": "gemini",
        "fallbacks": {"gemini": ["chatgpt"]},
        "providers": {
            "gemini": {"protocol": "opencli", "site": "gemini", "timeout": 180},
            "chatgpt": {"protocol": "opencli", "site": "chatgpt", "timeout": 180},
            "minimax": {
                "api_key": "sk-minimax",
                "base_url": "https://api.minimaxi.com/v1",
                "model": "MiniMax-M2.7",
                "protocol": "openai",
            },
        },
    }
    client = LLMClient(config)

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "MiniMax content"

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = response
        result = client.generate("system", "user")

    assert result == "MiniMax content"
