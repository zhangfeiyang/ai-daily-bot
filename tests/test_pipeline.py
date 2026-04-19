# tests/test_pipeline.py
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from src.models import NewsItem
from src.pipeline import Pipeline


def _make_items(n):
    return [
        NewsItem(
            source="test",
            title=f"News {i}",
            url=f"https://example.com/{i}",
            content=f"Content {i}",
            author="Author",
            published_at=datetime.now(timezone.utc),
            tags=["AI"],
            raw_data={},
        )
        for i in range(n)
    ]


def test_pipeline_deduplicate():
    items = _make_items(3)
    items.append(items[0])  # duplicate
    deduped = Pipeline._deduplicate(items)
    assert len(deduped) == 3


def test_pipeline_format_news():
    items = _make_items(2)
    text = Pipeline._format_news(items)
    assert "News 0" in text
    assert "News 1" in text


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_run_daily(mock_llm_cls, mock_tts_cls, mock_wechat_cls):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "<h1>AI 日报</h1><p>Content</p>"
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts.generate.return_value = "/tmp/test.mp3"
    mock_tts_cls.return_value = mock_tts

    mock_wechat = MagicMock()
    mock_wechat.upload_audio.return_value = "media_123"
    mock_wechat.publish_article.return_value = "pub_123"
    mock_wechat_cls.return_value = mock_wechat

    mock_crawler = MagicMock()
    mock_crawler.fetch.return_value = _make_items(3)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=mock_tts,
        publisher=mock_wechat,
    )

    result = pipeline.run()
    assert result is True
    mock_llm.generate.assert_called_once()
    mock_tts.generate.assert_called_once()
    mock_wechat.publish_article.assert_called_once()


def test_pipeline_crawler_failure_continues():
    """某个爬虫失败不影响其他爬虫。"""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "<p>article</p>"

    mock_tts = MagicMock()
    mock_tts.generate.return_value = "/tmp/test.mp3"

    mock_wechat = MagicMock()
    mock_wechat.upload_audio.return_value = "media_123"
    mock_wechat.publish_article.return_value = "pub_123"

    failing_crawler = MagicMock()
    failing_crawler.name = "FailingCrawler"
    failing_crawler.fetch.side_effect = Exception("Network error")

    working_crawler = MagicMock()
    working_crawler.name = "WorkingCrawler"
    working_crawler.fetch.return_value = _make_items(2)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[failing_crawler, working_crawler],
        llm_client=mock_llm,
        tts_engine=mock_tts,
        publisher=mock_wechat,
    )

    result = pipeline.run()
    assert result is True
    mock_llm.generate.assert_called_once()


def test_pipeline_no_items_returns_false():
    """没有爬取到任何内容时中止管道。"""
    mock_llm = MagicMock()

    empty_crawler = MagicMock()
    empty_crawler.name = "EmptyCrawler"
    empty_crawler.fetch.return_value = []

    pipeline = Pipeline(
        mode="daily",
        crawlers=[empty_crawler],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    result = pipeline.run()
    assert result is False
    mock_llm.generate.assert_not_called()
