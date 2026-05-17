# tests/test_pipeline.py
from datetime import datetime, timezone, timedelta
import re
import sys
import types
from unittest.mock import MagicMock, patch
from src.models import NewsItem
from src.crawlers.modelscope_crawler import ModelScopeCrawler
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
def test_pipeline_run_daily(mock_llm_cls, mock_tts_cls, mock_wechat_cls, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAILY_SECTION_WORKERS", "1")
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "0")
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "# 0510：AI 科技前沿\n\n**导读**\n- 一句话概括：今天的 AI 更新集中在模型、工具和应用。\n- 核心看点：先看每条新闻，再看它们合起来的方向。\n- 适合人群：关注 AI 行业动态的读者。\n\n## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1\n\n## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2\n\n## 第三条新闻\n\n内容三。\n\n参考链接：https://example.com/3\n\n## 第四条新闻\n\n内容四。\n\n参考链接：https://example.com/4\n\n## 第五条新闻\n\n内容五。\n\n参考链接：https://example.com/5\n\n所以，今天更值得看的不是某一个动作，而是它们一起把 AI 产品往前推了一步。"
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts.generate.return_value = "/tmp/test.mp3"
    mock_tts_cls.return_value = mock_tts

    mock_wechat = MagicMock()
    mock_wechat.upload_audio.return_value = "media_123"
    mock_wechat.publish_article.return_value = "pub_123"
    mock_wechat_cls.return_value = mock_wechat

    mock_crawler = MagicMock()
    mock_crawler.fetch.return_value = _make_items(5)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=mock_tts,
        publisher=mock_wechat,
        debug=True,
    )
    pipeline._fetch_search_context = MagicMock(return_value="")
    pipeline._enrich_items_with_page_media = MagicMock()
    pipeline._remove_ai_flavor = MagicMock(side_effect=lambda text: text)
    pipeline._generate_daily_section_drafts = MagicMock(return_value=[
        "## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1",
        "## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2",
        "## 第三条新闻\n\n内容三。\n\n参考链接：https://example.com/3",
        "## 第四条新闻\n\n内容四。\n\n参考链接：https://example.com/4",
        "## 第五条新闻\n\n内容五。\n\n参考链接：https://example.com/5",
    ])
    pipeline._compose_daily_synthesis_input = MagicMock(return_value="# draft")

    result = pipeline.run()
    assert result is True
    assert mock_llm.generate.call_count == 1
    mock_tts.generate.assert_not_called()
    mock_wechat.publish_article.assert_not_called()


def test_pipeline_crawler_failure_continues(tmp_path, monkeypatch):
    """某个爬虫失败不影响其他爬虫。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAILY_SECTION_WORKERS", "1")
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "0")
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
        debug=True,
    )
    pipeline._enrich_items_with_page_media = MagicMock()
    pipeline._fetch_search_context = MagicMock(return_value="")
    pipeline._remove_ai_flavor = MagicMock(side_effect=lambda text: text)
    pipeline._validate_daily_article_text = MagicMock(return_value=(True, []))
    pipeline._generate_daily_section_drafts = MagicMock(return_value=[
        "## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1",
        "## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2",
    ])
    pipeline._compose_daily_synthesis_input = MagicMock(return_value="# draft")
    mock_llm.generate.return_value = "# 0510：AI 科技前沿\n\n## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1\n\n## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2"

    result = pipeline.run()
    assert result is True
    assert mock_llm.generate.call_count == 1


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


def test_freshness_filter_drops_unparseable_timestamps():
    item = NewsItem(
        source="test",
        title="Unknown Timestamp",
        url="https://example.com/unknown",
        content="Content",
        author="Author",
        published_at="not-a-date",
        tags=["AI"],
        raw_data={},
    )

    assert Pipeline._filter_fresh_items([item], max_hours=24) == []


def test_modelscope_crawler_uses_real_publish_timestamp():
    crawler = ModelScopeCrawler({})
    item = crawler._parse_model(
        {
            "modelId": "Qwen/Qwen3.6-35B-A3B-MTP-GGUF",
            "author": "Qwen",
            "description": "test",
            "lastModified": "2026-05-06T12:30:00Z",
        }
    )

    assert item is not None
    assert item.published_at == datetime(2026, 5, 6, 12, 30, tzinfo=timezone.utc)


def test_daily_reference_links_stay_with_matching_section():
    items = [
        NewsItem(
            source="twitter",
            title="First",
            url="https://x.com/user/status/1",
            content="first",
            author="user",
            published_at=datetime.now(timezone.utc),
            tags=[],
            raw_data={"links": ["https://example.com/first"]},
        ),
        NewsItem(
            source="twitter",
            title="Second",
            url="https://x.com/user/status/2",
            content="second",
            author="user",
            published_at=datetime.now(timezone.utc),
            tags=[],
            raw_data={"links": ["https://example.com/second"]},
        ),
    ]
    article_html = (
        "<section><h2>第一条</h2></section><p>正文一</p>"
        "<section><h2>第二条</h2></section><p>正文二</p>"
    )

    result = Pipeline._append_daily_reference_links(
        article_html,
        items,
        section_items=items,
    )

    first_ref_pos = result.index("https://example.com/first")
    second_ref_pos = result.index("https://example.com/second")
    second_heading_pos = result.index("第二条")
    assert first_ref_pos < second_heading_pos
    assert second_ref_pos > second_heading_pos


def test_daily_reference_links_include_source_url_fallback():
    item = NewsItem(
        source="news",
        title="Fallback",
        url="https://example.com/source",
        content="content",
        author="author",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={},
    )
    article_html = "<section><h2>第一条</h2></section><p>正文</p>"

    result = Pipeline._append_daily_reference_links(article_html, [item], section_items=[item])

    assert "https://example.com/source" in result


def test_extract_items_from_article_sees_reference_section_links():
    item = NewsItem(
        source="twitter",
        title="OpenAI update",
        url="https://x.com/OpenAIDevs/status/123",
        content="content",
        author="OpenAIDevs",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={"links": ["https://x.com/OpenAIDevs/status/123"]},
    )
    article_html = (
        "<section><h2>第一条</h2></section><p>正文</p>"
        "<p style=\"color:#888;font-size:13px;margin:6px 0;line-height:1.6;\">参考："
        "<a href=\"https://x.com/OpenAIDevs/status/123\">https://x.com/OpenAIDevs/status/123</a></p>"
    )

    used = Pipeline._extract_items_from_article(article_html, [item])

    assert used == [(item, "https://x.com/OpenAIDevs/status/123")]


@patch("src.image.generator.ImageGenerator")
def test_generate_section_image_only_generates_once_per_article(mock_img_cls, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "1")

    img_file = tmp_path / "img.png"
    img_file.write_bytes(b"fake image")

    mock_gen = MagicMock()
    mock_gen.generate_illustration.return_value = img_file
    mock_img_cls.return_value = mock_gen

    mock_publisher = MagicMock()
    mock_publisher.upload_image.return_value = "https://wechat.example.com/img.png"

    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=mock_publisher,
    )

    first = pipeline._generate_section_image("第一条", "context", article_title="AI 科技前沿 | 2026-05-10")
    second = pipeline._generate_section_image("第二条", "context", article_title="AI 科技前沿 | 2026-05-10")

    assert first is not None
    assert second is None
    mock_gen.generate_illustration.assert_called_once()


@patch("src.image.generator.ImageGenerator")
def test_generate_section_image_only_attempts_once_per_article_after_failure(mock_img_cls, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "1")

    mock_gen = MagicMock()
    mock_gen.generate_illustration.side_effect = RuntimeError("provider timeout")
    mock_img_cls.return_value = mock_gen

    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    first = pipeline._generate_section_image("第一条", "context", article_title="AI 科技前沿 | 2026-05-10")
    second = pipeline._generate_section_image("第二条", "context", article_title="AI 科技前沿 | 2026-05-10")

    assert first is None
    assert second is None
    mock_gen.generate_illustration.assert_called_once()


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.LLMClient")
def test_pipeline_cover_generation_skips_ai_when_disabled(mock_llm_cls, mock_wechat_cls, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "0")

    mock_wechat = MagicMock()
    mock_wechat_cls.return_value = mock_wechat

    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        publisher=mock_wechat,
    )

    item = NewsItem(
        source="test",
        title="Feature Cover",
        url="https://example.com/cover",
        content="Cover content",
        author="Author",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )

    with patch("src.image.generator.ImageGenerator") as mock_image_gen:
        try:
            pipeline._get_cover_for_item(item, "2026-05-13", 1)
        except RuntimeError as e:
            assert "Feature cover requires generated image" in str(e)
        else:
            raise AssertionError("feature cover should require generated image")

    mock_image_gen.assert_not_called()


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_preselects_before_media_enrichment(mock_llm_cls, mock_tts_cls, mock_wechat_cls, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAILY_SECTION_WORKERS", "1")
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "0")
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
        debug=True,
    )

    selected = _make_items(10)
    pipeline._select_top_items = MagicMock(return_value=selected)
    pipeline._enrich_items_with_page_media = MagicMock()
    pipeline._fetch_search_context = MagicMock(return_value="")
    pipeline._generate_daily_section_drafts = MagicMock(return_value=["## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1"])
    pipeline._compose_daily_synthesis_input = MagicMock(return_value="# draft")
    mock_llm.generate.return_value = "# 0510：AI 科技前沿\n\n## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1"

    result = pipeline.run()
    assert result is True
    pipeline._select_top_items.assert_called_once()
    pipeline._enrich_items_with_page_media.assert_called_once_with(selected)


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_filters_domestic_sources_before_media_enrichment(mock_llm_cls, mock_tts_cls, mock_wechat_cls, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAILY_SECTION_WORKERS", "1")
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "0")

    official = NewsItem(
        source="github",
        title="OpenAI ships AI coding update",
        url="https://github.com/openai/example",
        content="AI coding update",
        author="OpenAI",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )
    domestic = NewsItem(
        source="china_ai",
        title="国内转载 OpenAI 新闻",
        url="https://www.qbitai.com/example",
        content="这是一条中文转载新闻",
        author="QbitAI",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )

    mock_llm = MagicMock()
    mock_llm.generate.return_value = "# 0510：AI 科技前沿\n\n## OpenAI ships AI coding update\n\n内容一。\n\n参考链接：https://github.com/openai/example"
    mock_llm_cls.return_value = mock_llm

    mock_crawler = MagicMock()
    mock_crawler.fetch.return_value = [official, domestic]

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=MagicMock(),
        debug=True,
    )
    pipeline._enrich_items_with_page_media = MagicMock()
    pipeline._generate_daily_section_drafts = MagicMock(return_value=[
        "## OpenAI ships AI coding update\n\n内容一。\n\n参考链接：https://github.com/openai/example"
    ])
    pipeline._compose_daily_synthesis_input = MagicMock(return_value="# draft")

    assert pipeline.run() is True
    pipeline._enrich_items_with_page_media.assert_called_once_with([official])
    pipeline._generate_daily_section_drafts.assert_called_once()
    assert pipeline._generate_daily_section_drafts.call_args.args[0] == [official]


def test_rank_social_items_keeps_highest_engagement_per_title():
    low = NewsItem(
        source="twitter",
        title="Same launch",
        url="https://x.com/a/status/1",
        content="low",
        author="a",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={"likes": 1, "replies": 0},
    )
    high = NewsItem(
        source="twitter",
        title="Same launch",
        url="https://x.com/b/status/1",
        content="high",
        author="b",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={"likes": 10, "replies": 2},
    )

    assert Pipeline._rank_social_items([low, high], limit=10) == [high]


def test_low_value_aggregator_items_are_filtered():
    item = NewsItem(
        source="duckduckgo",
        title="Ai早报 2026年05月13日 | Ai内参",
        url="https://example.com/ai-news",
        content="AI 新闻汇总",
        author="Search",
        published_at=datetime.now(timezone.utc),
        tags=["search"],
        raw_data={},
    )

    assert Pipeline._is_low_value_aggregator_item(item) is True


def test_generic_search_result_requires_primary_source():
    item = NewsItem(
        source="duckduckgo",
        title="Best LLMs May 2026",
        url="https://example-ranking-site.com/best-llms-may-2026",
        content="AI model roundup",
        author="Search",
        published_at=datetime.now(timezone.utc),
        tags=["search"],
        raw_data={},
    )

    assert Pipeline._is_low_value_aggregator_item(item) is True


def test_low_value_social_item_is_filtered():
    item = NewsItem(
        source="reddit",
        title="Father and daughter making breakfast together",
        url="https://reddit.com/r/pics/comments/1",
        content="AI generated image discussion",
        author="reddit",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={"score": 2000},
    )

    assert Pipeline._is_low_value_social_item(item) is True


@patch("requests.post")
def test_minimax_material_search_uses_direct_endpoint(mock_post, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    response = MagicMock()
    response.json.return_value = {
        "base_resp": {"status_code": 0},
        "organic": [
            {
                "title": "OpenAI update",
                "link": "https://openai.com/index/update",
                "snippet": "Official details",
                "date": "2026-05-13",
            },
            {
                "title": "Zhihu repost",
                "link": "https://zhuanlan.zhihu.com/p/123",
                "snippet": "slow repost",
            },
        ],
    }
    mock_post.return_value = response
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    results = pipeline._minimax_material_search(["OpenAI update"])

    assert results == [
        {
            "title": "OpenAI update",
            "url": "https://openai.com/index/update",
            "snippet": "Official details",
            "date": "2026-05-13",
            "_query": "OpenAI update",
            "_provider": "minimax",
        }
    ]
    assert mock_post.call_args.kwargs["json"] == {"q": "OpenAI update"}


@patch("requests.post")
def test_minimax_material_search_uses_persistent_cache(mock_post, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")
    monkeypatch.setenv("MINIMAX_MATERIAL_SEARCH_QUERIES", "1")

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "base_resp": {"status_code": 0},
        "organic": [{"title": "A", "link": "https://openai.com/a", "snippet": "alpha"}],
    }
    mock_post.return_value = response

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        publisher=MagicMock(),
    )

    first = pipeline._minimax_material_search(["OpenAI update"])
    second = pipeline._minimax_material_search(["OpenAI update"])

    assert first == second
    assert mock_post.call_count == 1
    assert (tmp_path / "output/material_cache.json").exists()


def test_fetch_page_assets_uses_persistent_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class Response:
        status_code = 200
        text = '<html><head><meta property="og:image" content="https://example.com/a.png"></head></html>'
        headers = {"content-type": "text/html"}

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        publisher=MagicMock(),
    )
    pipeline._fetch_page_response = MagicMock(return_value=Response())

    first = pipeline._fetch_page_assets("https://example.com/page")
    second = pipeline._fetch_page_assets("https://example.com/page")

    assert first == second
    assert first[0] == ["https://example.com/a.png"]
    pipeline._fetch_page_response.assert_called_once()


def test_describe_image_with_minimax_uses_persistent_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_MINIMAX_IMAGE_UNDERSTANDING", "1")

    client = MagicMock()
    client.understand_image.return_value = "图片摘要"
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        publisher=MagicMock(),
    )
    pipeline._minimax_mcp_client = client

    first = pipeline._describe_image_with_minimax("/tmp/a.png", "describe")
    second = pipeline._describe_image_with_minimax("/tmp/a.png", "describe")

    assert first == second == "图片摘要"
    client.understand_image.assert_called_once()


def test_select_top_items_deduplicates_repeated_llm_indices():
    llm = MagicMock()
    llm.generate.return_value = "1. best\n1. duplicate\n2. second\n"
    items = _make_items(3)
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=llm,
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    selected = pipeline._select_top_items(items, count=3)

    assert selected == [items[0], items[1]]


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


def test_feature_pipeline_stages_without_stream_upload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FEATURE_MAX_ARTICLES", "1")
    item = NewsItem(
        source="github",
        title="AI feature launch",
        url="https://github.com/example/launch",
        content="AI feature content",
        author="Example",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )

    crawler = MagicMock()
    crawler.name = "FeatureCrawler"
    crawler.fetch.return_value = [item]

    publisher = MagicMock()
    pipeline = Pipeline(
        mode="feature",
        crawlers=[crawler],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=publisher,
        debug=True,
    )
    pipeline._select_top_items = MagicMock(return_value=[item])
    pipeline._enrich_items_with_page_media = MagicMock()

    def fake_generate(task):
        i, _, today, output_dir = task
        article_path = output_dir / f"feature_{today}_{i}.html"
        article_path.write_text("<!-- ARTICLE_TITLE: AI feature launch -->\n<p>content</p>", encoding="utf-8")
        return i, article_path

    pipeline._generate_single_feature_article = MagicMock(side_effect=fake_generate)

    assert pipeline.run_feature() is True
    publisher.create_draft.assert_not_called()


def test_feature_pipeline_uploads_each_completed_article(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FEATURE_MAX_ARTICLES", "1")
    item = NewsItem(
        source="github",
        title="AI feature launch",
        url="https://github.com/example/launch",
        content="AI feature content",
        author="Example",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )

    crawler = MagicMock()
    crawler.name = "FeatureCrawler"
    crawler.fetch.return_value = [item]

    publisher = MagicMock()
    publisher.create_draft.return_value = "draft_123"
    pipeline = Pipeline(
        mode="feature",
        crawlers=[crawler],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=publisher,
        debug=True,
        upload_drafts=True,
    )
    pipeline._select_top_items = MagicMock(return_value=[item])
    pipeline._enrich_items_with_page_media = MagicMock()

    def fake_generate(task):
        i, _, today, output_dir = task
        article_path = output_dir / f"feature_{today}_{i}.html"
        article_path.write_text(
            "<!-- ARTICLE_TITLE: AI feature launch -->\n"
            "<!-- THUMB_MEDIA_ID: thumb_123 -->\n"
            "<p>content</p>",
            encoding="utf-8",
        )
        return i, article_path

    pipeline._generate_single_feature_article = MagicMock(side_effect=fake_generate)

    assert pipeline.run_feature() is True
    publisher.create_draft.assert_called_once()
    assert publisher.create_draft.call_args.kwargs["title"] == "AI feature launch"
    assert publisher.create_draft.call_args.kwargs["thumb_media_id"] == "thumb_123"


def test_feature_pipeline_filters_social_noise_before_selection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    good_item = NewsItem(
        source="github",
        title="AI feature launch",
        url="https://github.com/example/launch",
        content="AI feature content",
        author="Example",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )
    noisy_item = NewsItem(
        source="twitter",
        title="RT by @sama: A preview for Pro users: a new personal finance feature",
        url="https://x.com/sama/status/1",
        content="Retweeted content",
        author="sama",
        published_at=datetime.now(timezone.utc),
        tags=["twitter"],
        raw_data={},
    )

    crawler = MagicMock()
    crawler.name = "FeatureCrawler"
    crawler.fetch.return_value = [good_item, noisy_item]

    pipeline = Pipeline(
        mode="feature",
        crawlers=[crawler],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
        debug=True,
    )
    pipeline.verifier = None
    pipeline._enrich_items_with_page_media = MagicMock()
    pipeline._select_top_items = MagicMock(side_effect=lambda items, count=10: items[:count])
    pipeline._is_ai_related = MagicMock(return_value=True)
    pipeline._generate_single_article = MagicMock(return_value="<p>content</p>")
    pipeline._generate_chinese_title_from_article = MagicMock(return_value="AI feature launch")
    pipeline._review_and_fix_article = MagicMock(
        return_value=(
            "<p>content</p>",
            "AI feature launch",
            {"iterations": 0, "title_issues": [], "content_issues": [], "image_duplicates": []},
        )
    )
    pipeline._get_cover_for_item = MagicMock(return_value="")

    assert pipeline.run_feature() is True
    selected_titles = [item.title for item in pipeline._select_top_items.call_args.args[0]]
    assert selected_titles == ["AI feature launch"]
    assert pipeline._generate_single_article.call_count == 1


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


def test_normalize_page_asset_url_rejects_data_uri():
    assert Pipeline._normalize_page_asset_url(
        "https://arxiv.org/html/2605.12491v1",
        "data:image/png;base64,abc",
    ) == ""


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

    curl_get = MagicMock(return_value=solved)
    curl_module = types.SimpleNamespace(requests=types.SimpleNamespace(get=curl_get))

    with patch("requests.get", return_value=challenged), patch.dict(
        sys.modules,
        {"curl_cffi": curl_module, "curl_cffi.requests": curl_module.requests},
        clear=False,
    ):
        resp = Pipeline._fetch_page_response("https://openai.com/research/example")

    assert resp is solved
    assert curl_get.call_args.kwargs["impersonate"] == "chrome124"


def test_fetch_page_response_uses_opencli_browser_when_curl_cffi_missing():
    class Response:
        def __init__(self, status_code, text, headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    challenged = Response(403, "<html>cloudflare challenge</html>", {"cf-mitigated": "challenge"})

    with patch("requests.get", return_value=challenged), patch.dict(
        sys.modules,
        {"curl_cffi": None, "curl_cffi.requests": None},
        clear=False,
    ), patch("src.pipeline.fetch_html_via_opencli", return_value="<html>browser page</html>") as browser_fetch:
        resp = Pipeline._fetch_page_response("https://openai.com/research/example")

    assert resp.status_code == 200
    assert resp.text == "<html>browser page</html>"
    browser_fetch.assert_called_once()


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

    assert "anthropic.com/research/claude-personal-guidance" in article_html


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
    pipeline._find_duplicate_images_in_article = MagicMock(return_value=[])
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
    pipeline._find_duplicate_images_in_article = MagicMock(return_value=[])
    pipeline._replace_section_image_after_review = MagicMock(return_value=None)

    result = pipeline._review_and_repair_article_images(
        article_html,
        _make_items(1),
        "article text",
        article_title="Codex 大升级",
    )

    assert "demo.png" in result


def test_article_image_review_does_not_swallow_video_section():
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    article_html = """
    <section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e;font-size:18px;margin:0;">DeepSeek 演示</h2></section>
    <section style="text-align:center;margin:12px 0;"><video src="https://cdn.example.com/demo.mp4" controls="controls" style="max-width:100%;border-radius:8px;"></video></section>
    <p>DeepSeek 正文。</p>
    <section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e;font-size:18px;margin:0;">Gemini 办公</h2></section>
    <section style="text-align:center;margin:12px 0;"><img src="https://assets.example.com/gemini.png" style="max-width:100%;border-radius:8px;" /></section>
    <p>Gemini 正文。</p>
    """

    pipeline._review_article_image = MagicMock(return_value=False)
    pipeline._find_duplicate_images_in_article = MagicMock(return_value=[])
    pipeline._replace_section_image_after_review = MagicMock(
        return_value='<section style="text-align:center;margin:12px 0;"><img src="generated://gemini" style="max-width:100%;border-radius:8px;" /></section>'
    )

    result = pipeline._review_and_repair_article_images(
        article_html,
        _make_items(2),
        "article text",
        article_title="AI 科技前沿",
    )

    assert "https://cdn.example.com/demo.mp4" in result
    assert "Gemini 办公" in result
    assert "generated://gemini" in result


def test_insert_section_images_falls_back_when_all_verified_images_rejected(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_IMAGE_GENERATION", "1")
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
    pipeline._generate_section_image = MagicMock(
        return_value='<section style="text-align:center;margin:12px 0;"><img src="https://wechat.example/generated.png" style="max-width:100%;border-radius:8px;" /></section>'
    )
    pipeline._compute_image_feature_vector = MagicMock(return_value=None)

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

    assert "wechat.example/generated.png" in result


def test_markdown_to_html_renders_prominent_news_heading():
    html = Pipeline._markdown_to_html("## 第一条新闻\n正文")

    assert "background:#f7f9fc" in html
    assert "font-size:20px" in html
    assert "第一条新闻" in html


def test_markdown_to_html_normalizes_feature_lead_and_bold_headings():
    html = Pipeline._markdown_to_html(
        "**导读**\n"
        "•一句话概括：成本最高降低61%\n"
        "•核心看点：上下文卸载、任务画布\n\n"
        "开头正文。\n\n"
        "**两项核心技术：卸载与画布**\n\n"
        "正文内容。"
    )

    assert html.count("<h1") == 1
    assert "导读" in html
    assert "一句话概括" in html
    assert "display:flex" in html
    assert "<h2" in html
    assert "两项核心技术：卸载与画布" in html
    assert "&#8226;一句话概括" not in html


def test_markdown_to_html_normalizes_html_entity_bullets_in_lead():
    html = Pipeline._markdown_to_html(
        "**导读**\n"
        "&#8226;一句话概括：成本最高降低61%\n"
        "&#8226;核心看点：上下文卸载、任务画布\n"
    )

    assert html.count("display:flex") == 2
    assert "&#8226;一句话概括" not in html


def test_markdown_to_html_closes_lead_before_reference_links():
    html = Pipeline._markdown_to_html(
        "# 导读\n"
        "- 一句话概括：发生了什么\n"
        "- 核心看点：两个变化\n"
        "\n"
        "参考链接：https://github.com/example/lead\n"
        "\n"
        "## 第一条新闻\n正文"
    )

    assert html.index("</section>") < html.index("第一条新闻")
    assert html.index("第一条新闻") < html.index("参考资料")


def test_markdown_to_html_moves_bare_reference_domains_out_of_body():
    html = Pipeline._markdown_to_html(
        "正文内容。\n\n"
        "www.ithome.com/0/950/415.htm\n\n"
        "docs.openclaw.ai/zh-CN/concepts/memory-builtin"
    )

    assert "参考资料" in html
    assert 'href="https://www.ithome.com/0/950/415.htm"' not in html
    assert 'href="https://docs.openclaw.ai/zh-CN/concepts/memory-builtin"' in html
    assert html.count("border-left:4px solid #e94560") == 0


def test_markdown_to_html_strips_spurious_related_links_heading():
    html = Pipeline._markdown_to_html(
        "## 第一部分\n正文\n\n## 相关链接\n\n## 第二部分\n更多正文"
    )

    assert "相关链接" not in html
    assert html.count("<h2") == 2


def test_render_reference_links_splits_glued_urls():
    html = Pipeline._render_reference_links(
        [
            "github.com/anthropics/claude-code/blob/main/CHANGELOG.mdgithub.com/anthropics/claude-code/releases/tag/v2.1.141www.anthropic.com/product/claude-code",
        ]
    )

    assert html.count("<a href=") == 3
    assert "CHANGELOG.mdgithub.com" not in html


def test_render_reference_links_splits_known_glued_domains():
    html = Pipeline._render_reference_links(
        [
            "github.com/anthropics/claude-code/releases/tag/v2.1.141www.anthropic.com/product/claude-codebaike.sogou.com/v8261213.htm",
        ]
    )

    assert html.count("<a href=") == 2
    assert "claude-codebaike" not in html
    assert "baike.sogou" not in html


def test_render_reference_links_filters_low_value_repost_domains():
    html = Pipeline._render_reference_links(
        [
            "https://x.com/OpenAIDevs/status/1",
            "https://baike.sogou.com/v213883871.htm",
            "https://www.3elife.net/Art/internet/202503/12/101165.html",
        ]
    )

    assert "x.com/OpenAIDevs" in html
    assert "sogou" not in html
    assert "3elife" not in html


def test_sanitize_article_html_strips_unsupported_tags():
    html = Pipeline._sanitize_article_html(
        '<div onclick="x" style="margin:10px;color:red"><script>alert(1)</script>'
        '<section style="margin:0 0 10px 0;"><h1 style="font-size:18px">标题</h1></section>'
        '<iframe src="x"></iframe></div>'
    )

    assert "<script" not in html
    assert "<iframe" not in html
    assert "onclick" not in html
    assert "标题" in html


def test_finalize_article_html_prefers_existing_html():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    html = pipeline._finalize_article_html(
        '<section style="margin:0 0 10px 0;"><h1 style="font-size:18px">导读</h1>'
        '<div style="display:flex"><div>一句话概括</div></div></section>'
        '<p>正文</p>'
    )

    assert "十字路口报道" in html
    assert "【十字路口导读】" in html
    assert "display:flex" not in html
    assert "正文" in html


def test_finalize_article_html_rebuilds_bad_lead_from_label_paragraphs():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    html = pipeline._finalize_article_html(
        '<section><h1>导读</h1><div style="display:flex"><div>-</div></div>'
        '<div style="display:flex"><div>相关链接**</div></div></section>'
        '<p>导读：钩子机制终于不哑了，能弹出桌面通知。</p>'
        '<p>适合人群：Claude Code 重度用户。</p>'
        '<p>核心看点：桌面通知、企业安全、后台代理。</p>'
        '<p>正文内容。</p>'
    )

    assert html.count("导读") == 1
    assert ">-<" not in html
    assert "相关链接**" not in html
    assert "钩子机制终于不哑了" in html
    assert "正文内容" in html


def test_finalize_article_html_repairs_mixed_markdown_html():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    html = pipeline._finalize_article_html(
        '<section style="margin:0 0 28px 0;"><h1>导读</h1>'
        '<div style="display:flex"><div>一句话概括：Codex 更新了 Rust 版本</div></div>'
        '<div style="display:flex"><div>核心看点：Rust、alpha 版本、工具链</div></div>'
        '<div style="display:flex"><div>适合人群：Rust 开发者</div></div>'
        '</section>\n'
        '## <section>\n'
        '## 导读\n'
        '- **一句话概括**：重复导读\n'
        '## </section>\n'
        '## <section>\n'
        '凌晨五点，GitHub 仓库有了动静。\n'
        '## </section>\n'
        '## 为什么是 Rust\n'
        'Rust 以内存安全和高性能著称。'
    )

    assert "## <section>" not in html
    assert "重复导读" not in html
    assert "Codex 更新了 Rust 版本" in html
    assert "凌晨五点" in html
    assert "font-family:Georgia, Times New Roman, Times, serif" in html
    assert "border-bottom:2px solid rgb(127,127,127)" in html
    assert "为什么是 Rust" in html


def test_finalize_article_html_applies_xzyuan_feature_layout():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    html = pipeline._finalize_article_html(
        "【十字路口导读】OpenAI 把 ChatGPT、Codex 和 API 合并，超级应用大战正式开打。\n\n"
        "就在刚刚，OpenAI 内部又有大动作。\n\n"
        "## ChatGPT 和 Codex 合并，目标不是聊天\n\n"
        "这次调整最关键的地方，是把用户入口和开发者入口放到同一张桌子上。\n\n"
        "｜超级应用不是多一个按钮，而是把工作流吞进去。\n\n"
        "参考链接：https://example.com/a"
    )

    assert "十字路口报道" in html
    assert "【十字路口导读】" in html
    assert "background-color:rgb(248,248,248)" in html
    assert "font-family:Georgia, Times New Roman, Times, serif" in html
    assert "border-bottom:2px solid rgb(127,127,127)" in html
    assert "border-left:8px solid rgba(158,158,158,0.3)" in html
    assert "参考资料：" in html
    assert "相关链接" not in html


def test_apply_xzyuan_daily_style_uses_feature_layout():
    html = Pipeline._markdown_to_html(
        "# 今日AI快讯\n\n"
        "导读\n"
        "- 今天的 AI 更新集中在模型和智能体工具。\n\n"
        "## Codex 更新工作流\n\n"
        "OpenAI 把 Codex 的远程开发体验继续往前推了一步。\n\n"
        "参考：https://x.com/OpenAIDevs/status/123\n\n"
        "## 开源模型神仙打架：Gemma 4、DeepSeek V4、Kimi K2.6全来了\n\n"
        "开源模型更新继续提速。"
    )

    styled = Pipeline._apply_xzyuan_daily_style(html, "今天的 AI 更新集中在模型和智能体工具。")

    assert "十字路口报道" in styled
    assert "【十字路口导读】" in styled
    assert "font-family:Georgia, Times New Roman, Times, serif" in styled
    assert "border-bottom:2px solid rgb(127,127,127)" in styled
    assert "background:#f7f9fc;border-left:4px solid #e94560" not in styled
    assert "参考资料：" in styled
    assert "https://x.com/OpenAIDevs/status/123" in styled
    assert "开源模型神仙打架：Gemma 4、DeepSeek V4、Kimi K2.6全来了" in styled


def test_apply_xzyuan_daily_style_keeps_question_sentence_as_paragraph():
    html = Pipeline._markdown_to_html(
        "## 想象一下，AI看新闻，能判断\"这条消息会如何影响股价走势\"？\n\n"
        "正文继续。"
    )

    styled = Pipeline._apply_xzyuan_daily_style(html, "正文继续。")

    assert "想象一下，AI看新闻" in styled
    assert "font-family:Georgia, Times New Roman, Times, serif" not in styled


def test_move_social_screenshots_before_references():
    html = (
        "<p>正文</p>"
        "<section style=\"text-align:center;margin-left:8px;margin-right:8px;margin-bottom:24px;\">"
        "<img src=\"https://example.com/shot.png\" style=\"width:100%;height:auto;\" />"
        "</section>"
        "<section style=\"margin-right:8px;margin-bottom:0px;margin-left:8px;min-height:1em;text-align:left;line-height:1.75em;\">"
        "<span style=\"font-size:14px;color:rgb(136,136,136);letter-spacing:1px;\">参考资料：</span>"
        "</section>"
    )

    moved = Pipeline._move_social_screenshots_before_references(html)

    assert moved.index("shot.png") < moved.index("参考资料")


@patch("src.image.generator.ImageGenerator")
def test_daily_cover_generation_is_always_ai(mock_image_gen, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_publisher = MagicMock()
    mock_publisher.upload_thumb.return_value = "media_123"

    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=mock_publisher,
        debug=False,
    )
    pipeline.llm.generate_with_images = MagicMock()

    generated = tmp_path / "generated.png"
    generated.write_bytes(b"image")
    mock_image_gen.return_value.generate_cover.return_value = generated

    item = NewsItem(
        source="twitter",
        title="Tweet",
        url="https://x.com/example/status/1",
        content="content",
        author="author",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={"reference_images": ["https://example.com/news.png"]},
    )

    media_id = pipeline._generate_cover("2026-05-17", [item], "summary text")

    assert media_id == "media_123"
    mock_image_gen.return_value.generate_cover.assert_called_once()
    pipeline.llm.generate_with_images.assert_not_called()


def test_finalize_article_html_removes_duplicate_reporter_blocks():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    html = pipeline._finalize_article_html(
        '<section style="text-align:center;margin-bottom:0px;margin-top:8px;line-height:1.75em;">'
        '<span style="color:rgb(0,0,0);font-size:19px;letter-spacing:1px;"><strong>十字路口报道 编辑：AI前线</strong></span>'
        '</section>'
        '<section style="text-align:center;margin-bottom:0px;margin-top:8px;line-height:1.75em;">'
        '<span style="color:rgb(0,0,0);font-size:19px;letter-spacing:1px;"><strong>十字路口报道 编辑：AI前线</strong></span>'
        '</section>'
        '<p>正文内容。</p>'
    )

    assert "十字路口报道 编辑：AI前线" not in html
    assert "正文内容" in html


def test_feature_postprocess_rebuilds_references_and_inserts_screenshot(tmp_path):
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    pipeline.publisher.upload_image.return_value = "https://mmbiz.qpic.cn/test.png"

    from PIL import Image

    screenshot = tmp_path / "shot.png"
    Image.new("RGB", (400, 300), color="white").save(screenshot)

    pipeline._capture_feature_screenshot = MagicMock(return_value=str(screenshot))

    item = NewsItem(
        source="news",
        title="OpenAI update",
        url="https://example.com/original",
        content="Source body",
        author="Author",
        published_at=datetime.now(timezone.utc),
        raw_data={
            "official_url": "https://openai.com/index/reorg",
            "links": [
                "https://x.com/OpenAI/status/123",
                "https://wired.com/fake-link",
            ],
        },
    )

    html = (
        "<section style=\"margin:0 0 28px 0;\"><h1>导读</h1></section>"
        "<p>正文内容。</p>"
        "<section style=\"margin-right:8px;margin-bottom:0px;margin-left:8px;min-height:1em;text-align:left;line-height:1.75em;\">"
        "<span style=\"font-size:14px;color:rgb(136,136,136);letter-spacing:1px;\">参考资料：</span>"
        "</section>"
        "<section style=\"margin-right:8px;margin-bottom:0px;margin-left:8px;min-height:1em;text-align:left;line-height:1.75em;\">"
        "<span style=\"font-size:14px;color:rgb(136,136,136);letter-spacing:1px;\">"
        "<a href=\"https://wired.com/fake-link\" style=\"color:rgb(136,136,136);text-decoration:none;word-break:break-all;\">https://wired.com/fake-link</a>"
        "</span></section>"
    )

    result = pipeline._feature_postprocess_article_html(html, item, cache_namespace="test")

    assert "wired.com/fake-link" not in result
    assert "openai.com/index/reorg" in result
    assert "x.com/OpenAI/status/123" in result
    assert "https://mmbiz.qpic.cn/test.png" in result
    assert result.count("参考资料：") == 1


def test_feature_postprocess_strips_reference_source_aliases():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    pipeline._insert_feature_screenshot = MagicMock(side_effect=lambda html, item, cache_namespace="": html)

    item = NewsItem(
        source="news",
        title="OpenAI update",
        url="https://example.com/original",
        content="Source body",
        author="Author",
        published_at=datetime.now(timezone.utc),
        raw_data={"official_url": "https://openai.com/index/reorg"},
    )

    html = (
        "<p><span>正文内容。</span></p>"
        '<p style="margin-left:8px;"><span style="font-size:15px;">参考来源：</span></p>'
        '<p><span>• https://ithome.com/fake</span></p>'
        '<p><span>• https://openai.com/index/reorg</span></p>'
    )

    result = pipeline._feature_postprocess_article_html(html, item, cache_namespace="test")

    assert "正文内容。" in result
    assert "参考来源" not in result
    assert "ithome.com/fake" not in result
    assert result.count("参考资料：") == 1
    assert "https://openai.com/index/reorg" in result


def test_finalize_article_html_flattens_nested_spans_and_empty_blocks():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    html = pipeline._finalize_article_html(
        '<section style="margin-bottom:0px;"><section><section></section></section></section>'
        '<p><span style="font-size:16px;"><span style="color:red;">正文内容。</span></span></p>'
    )

    assert "<span" in html
    assert re.search(r"<span[^>]*>\s*<span", html) is None
    assert '<section style="margin-bottom:0px;"><section><section></section></section></section>' not in html
    assert "正文内容。" in html


def test_enrich_feature_x_links_falls_back_to_opencli_browser():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    item = NewsItem(
        source="news",
        title="Peter says he spent $1.3M on Codex",
        url="https://example.com/article",
        content="Peter says he spent $1.3M on Codex and the team is using more agentic workflows.",
        author="Author",
        published_at=datetime.now(timezone.utc),
        raw_data={},
    )

    html = (
        '<a href="https://x.com/peter/status/1234567890123456789">tweet</a>'
        '<p>Peter said the team is moving faster with Codex.</p>'
    )

    with patch("src.utils.opencli_search.twitter_search", return_value=[]), \
         patch("src.pipeline.fetch_html_via_opencli", return_value=(
             '<html><body>'
             '<a href="https://x.com/peter/status/1234567890123456789">x</a>'
             '<a href="https://x.com/peter/status/1234567890123456789/photo/1">photo</a>'
             '</body></html>'
         )):
        found = pipeline._enrich_feature_x_links(item, html)

    assert "https://x.com/peter/status/1234567890123456789" in found
    assert "https://x.com/peter/status/1234567890123456789" in item.raw_data["links"]


def test_capture_feature_screenshot_prefers_x_over_github(tmp_path):
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    item = NewsItem(
        source="news",
        title="OpenAI update",
        url="https://example.com/article",
        content="Source body",
        author="Author",
        published_at=datetime.now(timezone.utc),
        raw_data={
            "links": [
                "https://github.com/example/repo",
                "https://x.com/peter/status/1234567890123456789",
            ],
        },
    )
    x_path = tmp_path / "x.png"
    x_path.write_bytes(b"1")
    github_path = tmp_path / "github.png"
    github_path.write_bytes(b"1")

    with patch("src.utils.twitter_screenshot.TwitterScreenshot.capture", return_value=x_path) as x_cap, \
         patch("src.utils.github_screenshot.GitHubScreenshot.capture", return_value=github_path) as gh_cap:
        result = pipeline._capture_feature_screenshot(item)

    assert result == str(x_path)
    assert x_cap.call_count == 1
    assert gh_cap.call_count == 0


def test_finalize_article_html_strips_hash_from_lead():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    html = pipeline._finalize_article_html(
        "【十字路口导读】# Peter 的帖子把 Codex 带进了新的工作流时代。\n\n正文内容。"
    )

    assert "【十字路口导读】#" not in html
    assert "># Peter" not in html
    assert "Peter 的帖子把 Codex 带进了新的工作流时代。" in html


def test_clean_final_article_html_repairs_hash_headings_and_nested_caption():
    html = Pipeline._clean_final_article_html(
        '<section style="margin:34px 0 16px 0;"><h2># 任务隔离</h2></section>'
        '<p style="color:#374151;"># 并行执行带来的效率质变</p>'
        '<section style="text-align:center;margin:20px 0 16px 0;">'
        '<section style="color:#555;"><p>OpenAI Developers update</p></section>'
        '<img src="https://example.com/demo.png" style="max-width:100%;" />'
        '</section>'
    )

    assert "># 任务隔离<" not in html
    assert "任务隔离" in html
    assert "<p" not in html.split("并行执行带来的效率质变", 1)[0].split("任务隔离", 1)[-1]
    assert html.count("<h2") == 2
    assert "<section><p" not in html
    assert "OpenAI Developers update" in html


def test_clean_final_article_html_splits_merged_lead_items():
    html = Pipeline._clean_final_article_html(
        '<section><h1>导读</h1><div style="display:flex"><div>'
        '一句话概括：一核心看点：二适合人群：三'
        '</div></div></section><p>正文</p>'
    )

    assert html.count("display:flex") == 3
    assert "一句话概括：一</div>" in html
    assert "核心看点：二</div>" in html
    assert "适合人群：三</div>" in html


def test_clean_final_article_html_rebuilds_glued_related_link_card():
    html = Pipeline._clean_final_article_html(
        '<section><p>相关链接</p><p><a href="https://github.com/anthropics/claude-code/releases/tag/v2.1.141www.anthropic.com/product/claude-codebaike.sogou.com/v8261213.htm">bad</a></p></section>'
    )

    assert html.count("<a href=") == 2
    assert "v2.1.141www" not in html
    assert "claude-codebaike" not in html
    assert "baike.sogou" not in html


def test_markdown_inline_code_is_rendered_without_backticks():
    html = Pipeline._markdown_to_html("新增 `terminalSequence` 字段。")

    assert "<code" in html
    assert "`terminalSequence`" not in html


def test_ensure_lead_section_inserts_lead_card_when_missing():
    html = Pipeline._ensure_lead_section(
        "<p>正文内容</p>",
        "•一句话概括：发生了什么\n•核心看点：两三件事\n•适合人群：谁该读"
    )

    assert "导读" in html
    assert "display:flex" in html
    assert "正文内容" in html


def test_ensure_lead_section_synthesizes_from_existing_body():
    html = Pipeline._ensure_lead_section(
        '<p style="color:#374151;">Symphony 现在可以为每个任务启动独立运行的 Codex 智能体。</p>'
        '<section><h2>任务隔离</h2></section>'
        '<section><h2>并行执行</h2></section>',
        "正文没有显式导读",
    )

    assert "导读" in html
    assert "一句话概括：Symphony 现在可以为每个任务启动独立运行的 Codex 智能体。" in html
    assert "核心看点：任务隔离、并行执行" in html


def test_insert_image_block_falls_back_to_after_lead_section():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    html = (
        '<section><h1>导读</h1><div>lead</div></section>'
        '<p>正文一</p><p>正文二</p>'
    )

    result = pipeline._insert_image_block_near_best_position(
        html,
        "https://example.com/a.png",
        "some image",
    )

    assert result.index("a.png") > result.index("</section>")
    assert result.index("a.png") < result.index("<p>正文一</p>")


def test_get_cover_for_item_requires_generated_cover(tmp_path, monkeypatch):
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"fake image")
    mock_wechat = MagicMock()
    mock_wechat.upload_thumb.return_value = "media_123"

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=mock_wechat,
        debug=True,
    )
    item = NewsItem(
        source="changelog",
        title="Claude Code v2.1.141 发布",
        url="https://github.com/anthropics/claude-code/releases/tag/v2.1.141",
        content="Claude Code v2.1.141 发布",
        author="Claude Code",
        published_at=datetime.now(timezone.utc),
        tags=["claude-code"],
        raw_data={},
    )

    with patch("src.image.generator.ImageGenerator") as mock_image_gen:
        mock_gen = mock_image_gen.return_value
        mock_gen.generate_cover.return_value = generated
        media_id = pipeline._get_cover_for_item(item, "2026-05-14", 1)

    assert media_id == "media_123"
    mock_gen.generate_cover.assert_called_once()
    assert mock_gen.generate_cover.call_args.kwargs["output_path"].endswith("feature_2026-05-14_1_generated.png")
    mock_wechat.upload_thumb.assert_called_once()


def test_insert_section_images_handles_current_heading_style():
    mock_llm = MagicMock()
    mock_llm.generate_with_images.return_value = "1"
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=MagicMock(),
        debug=True,
    )
    pipeline._download_and_upload_image = MagicMock(
        return_value='<section style="text-align:center;margin:12px 0;"><img src="https://wechat.example/current.png" style="max-width:100%;border-radius:8px;" /></section>'
    )
    pipeline._compute_image_feature_vector = MagicMock(return_value=None)

    article_html = Pipeline._markdown_to_html("## 第一部分\n内容")
    item = NewsItem(
        source="test",
        title="第一部分",
        url="https://example.com/1",
        content="内容",
        author="Author",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={"benchmark_images": ["https://example.com/current.png"]},
    )

    result = pipeline._insert_section_images(article_html, [item], "article text", article_title="Daily")

    assert "wechat.example/current.png" in result
    assert result.index("wechat.example/current.png") < result.index("内容")


def test_duplicate_image_detection_uses_cosine_similarity():
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    pipeline._compute_image_phash = MagicMock(return_value=None)
    pipeline._compute_image_feature_vector = MagicMock(
        side_effect=[[1.0, 0.0, 0.0], [0.999, 0.001, 0.0]]
    )
    html = (
        '<section style="text-align:center;margin:12px 0;"><img src="https://example.com/a.png" style="max-width:100%;border-radius:8px;" /></section>'
        '<section style="text-align:center;margin:12px 0;"><img src="https://example.com/b.png" style="max-width:100%;border-radius:8px;" /></section>'
    )

    duplicates = pipeline._find_duplicate_images_in_article(html, cosine_threshold=0.99)

    assert duplicates == [("https://example.com/a.png", "https://example.com/b.png")]


def test_validate_daily_article_rejects_dialogue_like_output():
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    valid, issues = pipeline._validate_daily_article_text(
        "感谢你提供了这份对话历史。请问有什么具体需要我帮忙处理的吗？"
    )

    assert valid is False
    assert any("meta phrase" in issue for issue in issues)


def test_version_guard_catches_bare_opus_version_not_in_source():
    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )
    item = NewsItem(
        source="github",
        title="Claude Code v2.1.142",
        url="https://github.com/anthropics/claude-code/releases/tag/v2.1.142",
        content="Fast mode now uses Opus 4.7 by default.",
        author="Anthropic",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={},
    )

    assert "opus 3.5" in pipeline._verify_generated_versions("Fast 模式升级到 Opus 3.5。", item)


def test_clean_llm_output_strips_think_blocks():
    text = (
        "<think>用户要求我写一段日报。\n"
        "我需要先分析素材。</think>\n"
        "## 正常标题\n\n正文内容。"
    )

    cleaned = Pipeline._clean_llm_output(text)

    assert "<think" not in cleaned
    assert "用户要求" not in cleaned
    assert "正常标题" in cleaned


def test_fact_correction_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_DAILY_FACT_CORRECTION", raising=False)
    pipeline = Pipeline(
        mode="daily",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    text = "## 第一条\nGPT-5.5 是一个模型版本。\n" * 5

    assert pipeline._verify_facts_in_article(text) == text
    pipeline.llm.generate.assert_not_called()


def test_compute_image_phash_skips_huge_images(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("MAX_PIPELINE_IMAGE_PIXELS", "10")
    img_path = tmp_path / "large.png"
    Image.new("RGB", (20, 20), color="red").save(img_path)

    assert Pipeline._compute_image_phash(str(img_path)) is None


def test_review_and_repair_article_images_removes_captioned_duplicates(tmp_path, monkeypatch):
    from PIL import Image

    img1 = tmp_path / "shot1.png"
    img2 = tmp_path / "shot2.png"
    Image.new("RGB", (64, 64), color="red").save(img1)
    Image.new("RGB", (64, 64), color="blue").save(img2)

    html = (
        '<section style="text-align:center;margin:12px 0;">'
        '<p style="color:#555;font-size:13px;margin:6px 0 0 0;line-height:1.6;'
        'padding:8px 12px;background:#f8f9fa;border-radius:4px;text-align:left;">'
        "OpenAI Developers update"
        '</p><img src="https://example.com/shot1.png" style="max-width:100%;border-radius:8px;" />'
        "</section>"
        '<section style="text-align:center;margin:12px 0;">'
        '<p style="color:#555;font-size:13px;margin:6px 0 0 0;line-height:1.6;'
        'padding:8px 12px;background:#f8f9fa;border-radius:4px;text-align:left;">'
        "OpenAI Developers update"
        '</p><img src="https://example.com/shot2.png" style="max-width:100%;border-radius:8px;" />'
        "</section>"
    )

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=MagicMock(),
        debug=True,
    )
    monkeypatch.setattr(pipeline, "_compute_image_phash", MagicMock(return_value="ff00ff00ff00ff00"))
    monkeypatch.setattr(pipeline, "_compute_image_feature_vector", MagicMock(return_value=None))

    cleaned = pipeline._review_and_repair_article_images(html, [], "article text", "title")

    assert cleaned.count("<img src=") == 1
    assert "https://example.com/shot1.png" in cleaned or "https://example.com/shot2.png" in cleaned


def test_insert_twitter_screenshots_dedupes_source_urls(tmp_path, monkeypatch):
    from PIL import Image

    img_path = tmp_path / "tweet.png"
    Image.new("RGB", (120, 80), color="green").save(img_path)

    screenshot_mock = MagicMock()
    screenshot_mock.capture.return_value = img_path

    publisher = MagicMock()
    publisher.upload_image.return_value = "https://wechat.example.com/tweet.png"

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=publisher,
        debug=True,
    )

    item = NewsItem(
        source="twitter",
        title="OpenAI Developers update",
        url="https://x.com/OpenAIDevs/status/2054252221941121035",
        content="OpenAI Developers update",
        author="OpenAIDevs",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={
            "links": [
                "https://x.com/OpenAIDevs/status/2054252221941121035",
                "https://x.com/OpenAIDevs/status/2054252221941121035?ref=foo",
                "https://x.com/OpenAIDevs/status/2054252221941121035/photo/1",
            ],
        },
    )
    html = "<p>OpenAI 开发者更新。</p><p>继续讲 Symphony 的工作流变化。</p>"

    with patch("src.utils.twitter_screenshot.TwitterScreenshot", return_value=screenshot_mock), \
         patch.object(Pipeline, "_describe_image_with_minimax", return_value="OpenAI Developers update about Symphony and Codex"), \
         patch.object(Pipeline, "_compute_image_phash", return_value="ff00ff00ff00ff00"):
        result = pipeline._insert_twitter_screenshots(html, item)

    assert screenshot_mock.capture.call_count == 1
    assert result.count("https://wechat.example.com/tweet.png") == 1


def test_insert_twitter_screenshots_uses_minimax_summary_for_position(tmp_path, monkeypatch):
    from PIL import Image

    img_path = tmp_path / "tweet2.png"
    Image.new("RGB", (160, 100), color="purple").save(img_path)

    screenshot_mock = MagicMock()
    screenshot_mock.capture.return_value = img_path

    publisher = MagicMock()
    publisher.upload_image.return_value = "https://wechat.example.com/pos.png"

    pipeline = Pipeline(
        mode="feature",
        crawlers=[],
        llm_client=MagicMock(),
        tts_engine=MagicMock(),
        publisher=publisher,
        debug=True,
    )

    item = NewsItem(
        source="twitter",
        title="OpenAI Developers update",
        url="https://x.com/OpenAIDevs/status/2054252221941121035",
        content="OpenAI Developers update",
        author="OpenAIDevs",
        published_at=datetime.now(timezone.utc),
        tags=["AI"],
        raw_data={"links": []},
    )
    html = (
        "<p>这段在讲一个完全无关的背景。</p>"
        "<p>这里才在讲 Symphony、Codex 和 OpenAI 开发者工作流的变化。</p>"
        "<p>最后一段是别的内容。</p>"
    )

    with patch("src.utils.twitter_screenshot.TwitterScreenshot", return_value=screenshot_mock), \
         patch.object(Pipeline, "_describe_image_with_minimax", return_value="OpenAI developers update showing Symphony and Codex workflow"), \
         patch.object(Pipeline, "_compute_image_phash", return_value="ff00ff00ff00ff00"):
        result = pipeline._insert_twitter_screenshots(html, item)

    image_pos = result.index("https://wechat.example.com/pos.png")
    target_pos = result.index("这里才在讲 Symphony")
    tail_pos = result.index("最后一段是别的内容")

    assert target_pos < image_pos < tail_pos


def test_pipeline_retries_invalid_daily_generation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        "感谢你提供了这份对话历史。请问有什么具体需要我帮忙处理的吗？",
        "# 0510：AI 科技前沿\n\n开头先把结论放前面：今天的 AI 新闻不是单点更新，而是一起往工作流深处挪。\n\n## 第一条新闻\n内容一内容一内容一，说明它为什么重要，也顺手补一个具体使用场景。\n\n## 第二条新闻\n内容二内容二内容二，继续把细节讲清楚，让读者知道它会怎么改变日常使用。\n\n## 第三条新闻\n内容三内容三内容三，补上一个对比，交代这次和上一版差在哪。\n\n## 第四条新闻\n内容四内容四内容四，再加一句判断，避免文章只剩描述没有观点。\n\n## 第五条新闻\n内容五内容五内容五，用一个更贴近生活的例子收住这一段。\n\n结尾也要留一点余味，让文章像一篇完整的日报，而不是聊天回复。",
    ]

    mock_wechat = MagicMock()
    mock_wechat.upload_thumb.return_value = "thumb_123"

    mock_crawler = MagicMock()
    mock_crawler.name = "MockCrawler"
    mock_crawler.fetch.return_value = _make_items(3)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=mock_wechat,
        debug=True,
    )
    pipeline._fetch_search_context = MagicMock(return_value="")
    pipeline._generate_daily_section_drafts = MagicMock(return_value=[
        "## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1",
        "## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2",
        "## 第三条新闻\n\n内容三。\n\n参考链接：https://example.com/3",
        "## 第四条新闻\n\n内容四。\n\n参考链接：https://example.com/4",
        "## 第五条新闻\n\n内容五。\n\n参考链接：https://example.com/5",
    ])
    pipeline._compose_daily_synthesis_input = MagicMock(return_value="# draft")
    pipeline._remove_ai_flavor = MagicMock(side_effect=lambda text: text)
    pipeline._generate_daily_section_drafts = MagicMock(return_value=[
        "## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1",
        "## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2",
        "## 第三条新闻\n\n内容三。\n\n参考链接：https://example.com/3",
        "## 第四条新闻\n\n内容四。\n\n参考链接：https://example.com/4",
        "## 第五条新闻\n\n内容五。\n\n参考链接：https://example.com/5",
    ])
    pipeline._insert_section_images = MagicMock(side_effect=lambda html, *args, **kwargs: html)
    pipeline._insert_social_screenshots = MagicMock(side_effect=lambda html, *args, **kwargs: html)
    pipeline._review_and_repair_article_images = MagicMock(side_effect=lambda html, *args, **kwargs: html)
    pipeline._append_daily_reference_links = MagicMock(side_effect=lambda html, *args, **kwargs: html)

    result = pipeline.run()

    assert result is True
    assert mock_llm.generate.call_count == 2


def test_pipeline_falls_back_when_llm_generation_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAILY_SECTION_WORKERS", "1")

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("502")

    mock_wechat = MagicMock()
    mock_wechat.upload_thumb.return_value = "thumb_123"

    mock_crawler = MagicMock()
    mock_crawler.name = "MockCrawler"
    mock_crawler.fetch.return_value = _make_items(5)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=mock_wechat,
        debug=True,
    )
    pipeline._remove_ai_flavor = MagicMock(side_effect=lambda text: text)
    pipeline._generate_daily_section_drafts = MagicMock(return_value=[
        "## 第一条新闻\n\n内容一。\n\n参考链接：https://example.com/1",
        "## 第二条新闻\n\n内容二。\n\n参考链接：https://example.com/2",
        "## 第三条新闻\n\n内容三。\n\n参考链接：https://example.com/3",
        "## 第四条新闻\n\n内容四。\n\n参考链接：https://example.com/4",
        "## 第五条新闻\n\n内容五。\n\n参考链接：https://example.com/5",
    ])
    pipeline._insert_section_images = MagicMock(side_effect=lambda html, *args, **kwargs: html)
    pipeline._insert_social_screenshots = MagicMock(side_effect=lambda html, *args, **kwargs: html)
    pipeline._review_and_repair_article_images = MagicMock(side_effect=lambda html, *args, **kwargs: html)
    pipeline._append_daily_reference_links = MagicMock(side_effect=lambda html, *args, **kwargs: html)

    result = pipeline.run()

    assert result is True
    assert mock_llm.generate.call_count == 3


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
