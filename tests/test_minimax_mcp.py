from __future__ import annotations

from src.minimax_mcp import MiniMaxMCPClient


def test_understand_image_uses_image_url_argument(monkeypatch):
    client = MiniMaxMCPClient(api_key="test-key", api_host="https://api.minimaxi.com", command=["python", "-c", "print('x')"], timeout=1)
    called = {}

    def fake_call(tool_name: str, arguments: dict):
        called["tool_name"] = tool_name
        called["arguments"] = arguments
        return {"content": [{"type": "text", "text": "a test description"}]}

    monkeypatch.setattr(client, "_call_tool", fake_call)

    text = client.understand_image("describe", "/tmp/image.png")

    assert text == "a test description"
    assert called["tool_name"] == "understand_image"
    assert called["arguments"] == {"prompt": "describe", "image_url": "/tmp/image.png"}


def test_understand_image_prefers_direct_vlm(monkeypatch):
    client = MiniMaxMCPClient(api_key="test-key", api_host="https://api.minimaxi.com", command=["python", "-c", "print('x')"], timeout=1)
    called = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": "direct description", "base_resp": {"status_code": 0, "status_msg": "success"}}

    def fake_post(url, json, headers, timeout):
        called["url"] = url
        called["json"] = json
        called["timeout"] = timeout
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(client, "_call_tool", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("MCP fallback should not run")))

    text = client.understand_image("describe", "https://example.com/image.png")

    assert text == "direct description"
    assert called["url"] == "https://api.minimaxi.com/v1/coding_plan/vlm"
    assert called["json"] == {"prompt": "describe", "image_url": "https://example.com/image.png"}


def test_understand_image_falls_back_to_mcp_when_direct_fails(monkeypatch):
    client = MiniMaxMCPClient(api_key="test-key", api_host="https://api.minimaxi.com", command=["python", "-c", "print('x')"], timeout=1)
    called = {}

    def fake_post(*args, **kwargs):
        raise TimeoutError("vlm timeout")

    def fake_call(tool_name: str, arguments: dict):
        called["tool_name"] = tool_name
        called["arguments"] = arguments
        return {"content": [{"type": "text", "text": "fallback description"}]}

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(client, "_call_tool", fake_call)

    text = client.understand_image("describe", "/tmp/image.png")

    assert text == "fallback description"
    assert called["tool_name"] == "understand_image"
    assert called["arguments"] == {"prompt": "describe", "image_url": "/tmp/image.png"}
