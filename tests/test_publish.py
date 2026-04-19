# tests/test_publish.py
from unittest.mock import patch, MagicMock
from src.publish.wechat import WeChatPublisher
import tempfile
import os


def test_wechat_get_access_token():
    config = {"app_id": "wx123", "app_secret": "secret123"}
    publisher = WeChatPublisher(config)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "token_abc", "expires_in": 7200}
    mock_resp.raise_for_status = MagicMock()

    with patch("src.publish.wechat.requests.get", return_value=mock_resp):
        token = publisher._get_access_token()
        assert token == "token_abc"


@patch("src.publish.wechat.requests.post")
@patch("src.publish.wechat.requests.get")
def test_wechat_upload_audio(mock_get, mock_post):
    config = {"app_id": "wx123", "app_secret": "secret123"}
    publisher = WeChatPublisher(config)

    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "tok123", "expires_in": 7200}
    mock_token_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_token_resp

    mock_upload_resp = MagicMock()
    mock_upload_resp.json.return_value = {"media_id": "media_abc"}
    mock_upload_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_upload_resp

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"fake mp3")
        audio_path = f.name

    try:
        media_id = publisher.upload_audio(audio_path)
        assert media_id == "media_abc"
    finally:
        os.unlink(audio_path)


@patch("src.publish.wechat.requests.post")
@patch("src.publish.wechat.requests.get")
def test_wechat_publish_article(mock_get, mock_post):
    config = {"app_id": "wx123", "app_secret": "secret123"}
    publisher = WeChatPublisher(config)

    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "tok123", "expires_in": 7200}
    mock_token_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_token_resp

    mock_draft_resp = MagicMock()
    mock_draft_resp.json.return_value = {"media_id": "draft_123"}
    mock_draft_resp.raise_for_status = MagicMock()

    mock_pub_resp = MagicMock()
    mock_pub_resp.json.return_value = {"publish_id": "pub_123"}
    mock_pub_resp.raise_for_status = MagicMock()

    mock_post.side_effect = [mock_draft_resp, mock_pub_resp]

    result = publisher.publish_article(
        title="AI 日报",
        content="<p>Test content</p>",
        audio_media_id="media_abc",
        thumb_media_id="thumb_abc",
    )
    assert result == "pub_123"
