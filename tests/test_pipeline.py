# tests/test_pipeline.py
from datetime import datetime, timezone, timedelta
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
    assert mock_llm.generate.call_count >= 1
    mock_tts.generate.assert_not_called()
    mock_wechat.publish_article.assert_not_called()


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
    assert mock_llm.generate.call_count >= 1


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


def test_pipeline_filters_stale_items_before_selection():
    fresh_item = NewsItem(
        source="test",
        title="Fresh News",
        url="https://example.com/fresh",
        content="Fresh content",
        author="Author",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )
    stale_item = NewsItem(
        source="test",
        title="Stale News",
        url="https://example.com/stale",
        content="Stale content",
        author="Author",
        published_at=datetime.now(timezone.utc) - timedelta(hours=25),
        tags=["AI"],
        raw_data={},
    )

    filtered = Pipeline._filter_fresh_items([fresh_item, stale_item], max_hours=24)

    assert filtered == [fresh_item]


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_preselects_before_media_enrichment(mock_llm_cls, mock_tts_cls, mock_wechat_cls):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "<h1>AI 日报</h1><p>Content</p>"
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts_cls.return_value = mock_tts

    mock_wechat = MagicMock()
    mock_wechat.publish_article.return_value = "pub_123"
    mock_wechat_cls.return_value = mock_wechat

    mock_crawler = MagicMock()
    mock_crawler.fetch.return_value = _make_items(20)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=mock_tts,
        publisher=mock_wechat,
    )

    selected = _make_items(15)
    pipeline._select_top_items = MagicMock(return_value=selected)
    pipeline._enrich_items_with_page_media = MagicMock()

    result = pipeline.run()
    assert result is True
    pipeline._select_top_items.assert_called_once()
    pipeline._enrich_items_with_page_media.assert_called_once_with(selected)


def test_feature_pipeline_filters_stale_items_before_selection():
    fresh_item = NewsItem(
        source="test",
        title="Fresh Feature",
        url="https://example.com/fresh-feature",
        content="Fresh feature content",
        author="Author",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )
    stale_item = NewsItem(
        source="test",
        title="Stale Feature",
        url="https://example.com/stale-feature",
        content="Stale feature content",
        author="Author",
        published_at=datetime.now(timezone.utc) - timedelta(hours=25),
        tags=["AI"],
        raw_data={},
    )

    filtered = Pipeline._filter_fresh_items([fresh_item, stale_item], max_hours=24)

    assert filtered == [fresh_item]


def test_pipeline_formats_twitter_comments_in_news_block():
    item = NewsItem(
        source="twitter",
        title="Tweet",
        url="https://x.com/OpenAI/status/1",
        content="Content",
        author="OpenAI",
        published_at=datetime.now(timezone.utc),
        tags=["twitter"],
        raw_data={
            "comments": [
                {
                    "author": "@OpenAI",
                    "text": "官方补充了图表说明",
                    "likes": 12,
                    "replies": 3,
                    "images": ["https://pbs.twimg.com/media/chart.png"],
                    "url": "https://x.com/OpenAI/status/2",
                }
            ]
        },
    )

    text = Pipeline._format_news([item])

    assert "热门评论" in text
    assert "官方补充了图表说明" in text
    assert "chart.png" in text


def test_collect_item_media_includes_comment_images_and_videos():
    item = NewsItem(
        source="twitter",
        title="Tweet",
        url="https://x.com/OpenAI/status/1",
        content="Content",
        author="OpenAI",
        published_at=datetime.now(timezone.utc),
        tags=["twitter"],
        raw_data={
            "image_url": "https://pbs.twimg.com/media/main.png",
            "comment_images": ["https://pbs.twimg.com/media/comment.png"],
            "video_urls": ["https://video.example/main.mp4"],
            "comment_video_urls": ["https://video.example/comment.mp4"],
        },
    )

    media = Pipeline._collect_item_media(item)

    assert "https://pbs.twimg.com/media/main.png" in media["images"]
    assert "https://pbs.twimg.com/media/comment.png" in media["images"]
    assert "https://video.example/main.mp4" in media["videos"]
    assert "https://video.example/comment.mp4" in media["videos"]


def test_collect_item_media_prioritizes_reference_images():
    item = NewsItem(
        source="china_ai",
        title="Anthropic research",
        url="https://qbitai.com/article",
        content="Content",
        author="QbitAI",
        published_at=datetime.now(timezone.utc),
        tags=["china-ai"],
        raw_data={
            "reference_images": ["https://example.com/ref.png"],
            "official_image": "https://example.com/official.png",
            "image_url": "https://example.com/news.png",
            "benchmark_images": ["https://example.com/bench.png"],
        },
    )

    media = Pipeline._collect_item_media(item)

    assert media["images"][0] == "https://example.com/ref.png"


def test_enrich_items_with_page_media_marks_reference_images():
    item = NewsItem(
        source="china_ai",
        title="Anthropic research",
        url="https://qbitai.com/article",
        content="Content",
        author="QbitAI",
        published_at=datetime.now(timezone.utc),
        tags=["china-ai"],
        raw_data={
            "links": ["https://www.anthropic.com/research/claude-personal-guidance"],
        },
    )

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    pipeline._should_fetch_assets_for_item = MagicMock(return_value=True)
    pipeline._fetch_page_assets = MagicMock(
        return_value=(
            ["https://www.anthropic.com/image/chart.png"],
            [],
            [],
        )
    )
    pipeline._enrich_twitter_comments = MagicMock()

    pipeline._enrich_items_with_page_media([item])

    assert item.raw_data["reference_images"] == ["https://www.anthropic.com/image/chart.png"]
    assert item.raw_data["benchmark_images"] == ["https://www.anthropic.com/image/chart.png"]


def test_normalize_page_asset_url_extracts_next_image_source():
    asset_url = (
        "/_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2Fchart.png"
        "&w=3840&q=75"
    )

    assert Pipeline._normalize_page_asset_url("https://www.anthropic.com/research/x", asset_url) == (
        "https://www-cdn.anthropic.com/images/chart.png"
    )


def test_should_fetch_assets_for_official_research_pages():
    item = NewsItem(
        source="china_ai",
        title="Anthropic 发布研究",
        url="https://qbitai.com/article",
        content="官方研究页有图表和详细说明",
        author="QbitAI",
        published_at=datetime.now(timezone.utc),
        tags=["china-ai"],
        raw_data={
            "links": ["https://www.anthropic.com/research/claude-personal-guidance"],
        },
    )

    assert Pipeline._should_fetch_assets_for_item(
        item,
        "https://www.anthropic.com/research/claude-personal-guidance",
    ) is True


def test_fetch_page_response_uses_curl_cffi_on_cloudflare_challenge():
    class Response:
        def __init__(self, status_code, text, headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    challenged = Response(403, "<html>cloudflare challenge</html>", {"cf-mitigated": "challenge"})
    solved = Response(200, "<html>official page</html>", {"content-type": "text/html"})

    with patch("requests.get", return_value=challenged), patch(
        "curl_cffi.requests.get",
        return_value=solved,
    ) as curl_get:
        resp = Pipeline._fetch_page_response("https://openai.com/research/example")

    assert resp is solved
    assert curl_get.call_args.kwargs["impersonate"] == "chrome124"


@patch("src.pipeline.LLMClient")
def test_generate_single_article_keeps_raw_reference_links(mock_llm_cls):
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        "## 研究结论\n内容",
        "## 研究结论\n内容",
        "## 研究结论\n内容",
    ]
    mock_llm.generate_with_images.return_value = "YES"
    mock_llm_cls.return_value = mock_llm

    mock_wechat = MagicMock()
    mock_wechat.upload_image.return_value = "https://wechat.example/image.png"

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=mock_wechat,
        debug=True,
    )
    pipeline._fetch_page_assets = MagicMock(return_value=([], [], []))
    pipeline._remove_ai_flavor = MagicMock(side_effect=lambda text: text)

    item = NewsItem(
        source="china_ai",
        title="Anthropic research",
        url="https://qbitai.com/article",
        content="Content",
        author="QbitAI",
        published_at=datetime.now(timezone.utc),
        tags=["china-ai"],
        raw_data={
            "links": ["https://www.anthropic.com/research/claude-personal-guidance"],
            "full_content": "<p>content</p>",
        },
    )

    article_html = pipeline._generate_single_article(item, "2026-05-01")

    assert "https://www.anthropic.com/research/claude-personal-guidance" in article_html


def test_article_image_review_can_replace_low_value_image():
    mock_llm = MagicMock()
    mock_wechat = MagicMock()
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=mock_wechat,
    )

    article_html = """
    <section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e;font-size:18px;border-left:4px solid #e94560;padding-left:10px;margin:0;">DeepSeek 新模型</h2></section>
    <section style="text-align:center;margin:12px 0;"><img src="https://i.qbitai.com/wp-content/uploads/2026/04/bad.png" style="max-width:100%;border-radius:8px;" /></section>
    <p>正文内容</p>
    """

    pipeline._review_article_image = MagicMock(return_value=False)
    pipeline._replace_section_image_after_review = MagicMock(
        return_value='<section style="text-align:center;margin:12px 0;"><img src="https://example.com/replacement.png" style="max-width:100%;border-radius:8px;" /></section>'
    )

    result = pipeline._review_and_repair_article_images(
        article_html,
        _make_items(1),
        "article text",
        article_title="AI 科技前沿 | 2026-05-01",
    )

    assert "replacement.png" in result
    assert "bad.png" not in result


def test_article_image_review_keeps_original_when_no_replacement():
    mock_llm = MagicMock()
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    article_html = """
    <section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e;font-size:18px;border-left:4px solid #e94560;padding-left:10px;margin:0;">Codex 实测</h2></section>
    <section style="text-align:center;margin:12px 0;"><img src="https://example.com/demo.png" style="max-width:100%;border-radius:8px;" /></section>
    <p>正文内容</p>
    """

    pipeline._review_article_image = MagicMock(return_value=False)
    pipeline._replace_section_image_after_review = MagicMock(return_value=None)

    result = pipeline._review_and_repair_article_images(
        article_html,
        _make_items(1),
        "article text",
        article_title="Codex 大升级",
    )

    assert "demo.png" in result


def test_insert_section_images_falls_back_when_all_verified_images_rejected():
    mock_llm = MagicMock()
    mock_llm.generate_with_images.return_value = "NO"
    mock_wechat = MagicMock()
    mock_wechat.upload_image.return_value = "https://wechat.example/image.png"

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=mock_wechat,
    )
    pipeline._download_and_upload_image = MagicMock(
        return_value='<section style="text-align:center;margin:12px 0;"><img src="https://wechat.example/image.png" style="max-width:100%;border-radius:8px;" /></section>'
    )

    article_html = (
        '<h1 style="color:#1a1a2e;font-size:22px;text-align:center;">标题</h1>'
        '<p style="color:#333;line-height:1.8;margin:8px 0;">正文</p>'
        '<section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e;font-size:18px;border-left:4px solid #e94560;padding-left:10px;margin:0;">第一部分</h2></section>'
        '<p style="color:#333;line-height:1.8;margin:8px 0;">内容</p>'
    )
    item = NewsItem(
        source="china_ai",
        title="How do people seek guidance from Claude?",
        url="https://qbitai.com/article",
        content="Content",
        author="QbitAI",
        published_at=datetime.now(timezone.utc),
        tags=["china-ai"],
        raw_data={
            "benchmark_images": ["https://example.com/official.png"],
        },
    )

    result = pipeline._insert_section_images(article_html, [item], "article text", article_title="Claude")

    assert "wechat.example/image.png" in result


class TestArticleReviewLoop:
    """Tests for the comprehensive article review loop."""

    def test_review_title_detects_truncated(self):
        """标题审查应检测截断标题。"""
        ok, issues = Pipeline._review_title("%勒索率归零", "original")
        assert not ok
        assert any("截断" in i for i in issues)

    def test_review_title_detects_english_mix(self):
        """标题审查应检测非专有名词的英文混用。"""
        ok, issues = Pipeline._review_title("这个AI工具very好用", "original")
        assert not ok
        assert any("very" in i for i in issues)

    def test_review_title_allows_proper_nouns(self):
        """标题审查应允许专有名词英文。"""
        ok, issues = Pipeline._review_title("OpenAI发布GPT-5新功能", "original")
        assert ok
        assert len(issues) == 0

    def test_review_content_fallback_detects_ai_flavor(self):
        """内容审查回退应检测 AI 套话。"""
        text = "值得注意的是，这个模型非常强大。总的来说，AI的未来可期。"
        ok, issues = Pipeline._review_content_fallback(text)
        assert not ok
        assert len(issues) >= 2

    def test_find_duplicate_images_empty(self):
        """无图片时应返回空列表。"""
        html = "<p>no images</p>"
        pipeline = Pipeline(
            mode="feature",
            crawlers=[],
            llm_client=MagicMock(),
            tts_engine=MagicMock(),
            publisher=MagicMock(),
        )
        dups = pipeline._find_duplicate_images_in_article(html)
        assert dups == []

    def test_compute_phash_local_file(self, tmp_path):
        """感知哈希应能处理本地图片文件。"""
        from PIL import Image

        # Create a simple test image
        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (100, 100), color="red")
        img.save(img_path)

        phash = Pipeline._compute_image_phash(str(img_path))
        assert phash is not None
        assert len(phash) > 0
