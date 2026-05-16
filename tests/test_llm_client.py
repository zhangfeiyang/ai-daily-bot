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


def test_llm_client_falls_back_to_minimax():
    config = {
        "default": "custom",
        "fallbacks": {"custom": ["minimax"]},
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

    primary_client = MagicMock()
    primary_client.chat.completions.create.side_effect = RuntimeError("primary failed")

    fallback_response = MagicMock()
    fallback_response.choices = [MagicMock()]
    fallback_response.choices[0].message.content = "MiniMax fallback content"
    fallback_client = MagicMock()
    fallback_client.chat.completions.create.return_value = fallback_response

    def fake_openai(api_key=None, base_url=None, timeout=None):
        if base_url == "https://custom.example/v1":
            return primary_client
        if base_url == "https://api.minimaxi.com/v1":
            return fallback_client
        raise AssertionError(f"unexpected base_url: {base_url}")

    with patch("openai.OpenAI", side_effect=fake_openai):
        result = client.generate("system prompt", "user prompt")

    assert result == "MiniMax fallback content"
    assert primary_client.chat.completions.create.called
    assert fallback_client.chat.completions.create.called


def test_llm_client_strips_think_blocks():
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


def test_llm_client_generate_opencli_provider():
    config = {
        "default": "gemini",
        "providers": {
            "gemini": {
                "protocol": "opencli",
                "site": "gemini",
                "timeout": 180,
                "new": True,
            }
        },
    }
    client = LLMClient(config)

    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "生成内容"
    proc.stderr = ""

    with patch("src.llm.client.subprocess.run", return_value=proc) as mock_run:
        result = client.generate("system prompt", "user prompt")

    assert result == "生成内容"
    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["opencli", "gemini", "ask"]
    assert "--timeout" in cmd
    assert "-f" in cmd
    assert "plain" in cmd
    assert "--new" in cmd


def test_generate_with_images_opencli_deepseek_file(tmp_path):
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

    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "YES"
    proc.stderr = ""

    with patch("src.llm.client.subprocess.run", return_value=proc) as mock_run:
        result = client.generate_with_images("system", "text", [str(image)])

    assert result == "YES"
    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["opencli", "deepseek", "ask"]
    assert "--model" in cmd
    assert "vision" in cmd
    assert "--file" in cmd
    assert str(image) in cmd
