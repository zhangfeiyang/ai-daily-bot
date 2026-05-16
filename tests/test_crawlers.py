# tests/test_crawlers.py
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.crawlers.base import BaseCrawler
from src.crawlers.arxiv_crawler import ArxivCrawler
from src.models import NewsItem


class DummyCrawler(BaseCrawler):
    def _fetch(self):
        return [
            NewsItem(
                source="test",
                title="t",
                url="https://example.com",
                content="c",
                author="a",
                published_at=datetime.now(timezone.utc),
            )
        ]


def test_base_crawler_fetch_raises():
    try:
        crawler = BaseCrawler({})
        assert False, "Should have raised TypeError"
    except TypeError:
        pass


def test_base_crawler_name():
    crawler = DummyCrawler({"key": "val"})
    assert crawler.name == "DummyCrawler"


def test_arxiv_crawler_parse_result():
    mock_result = MagicMock()
    mock_result.entry_id = "http://arxiv.org/abs/2401.00001v1"
    mock_result.title = "  A Great Paper on AI  "
    mock_result.summary = "This is the abstract."
    mock_result.authors = [MagicMock(name="Alice"), MagicMock(name="Bob")]
    mock_result.authors[0].name = "Alice"
    mock_result.authors[1].name = "Bob"
    mock_result.published = datetime(2026, 4, 19, 8, 0, 0, tzinfo=timezone.utc)
    mock_result.categories = ["cs.AI", "cs.CL"]
    mock_result.pdf_url = "https://arxiv.org/pdf/2401.00001v1"

    crawler = ArxivCrawler({
        "enabled": True,
        "categories": ["cs.AI"],
        "max_results": 5,
        "sort_by": "submittedDate",
    })
    items = crawler._parse_result(mock_result)
    assert isinstance(items, NewsItem)
    assert items.source == "arxiv"
    assert items.title == "A Great Paper on AI"
    assert items.author == "Alice, Bob"
    assert "cs.AI" in items.tags


@patch("src.crawlers.arxiv_crawler.arxiv")
def test_arxiv_crawler_fetch(mock_arxiv_mod):
    mock_client = MagicMock()
    mock_arxiv_mod.Client.return_value = mock_client
    mock_arxiv_mod.SortCriterion.SubmittedDate = "submittedDate"

    mock_result = MagicMock()
    mock_result.entry_id = "http://arxiv.org/abs/2401.00001v1"
    mock_result.title = "Test Paper"
    mock_result.summary = "Abstract"
    mock_result.authors = [MagicMock(name="Author")]
    mock_result.authors[0].name = "Author"
    mock_result.published = datetime(2026, 4, 19, tzinfo=timezone.utc)
    mock_result.categories = ["cs.AI"]
    mock_result.pdf_url = "https://arxiv.org/pdf/2401.00001v1"
    mock_client.results.return_value = iter([mock_result])

    crawler = ArxivCrawler({
        "enabled": True,
        "categories": ["cs.AI"],
        "max_results": 5,
        "sort_by": "submittedDate",
    })
    crawler.cache_ttl_seconds = None
    items = crawler.fetch()
    assert len(items) == 1
    assert items[0].source == "arxiv"


from src.crawlers.reddit_crawler import RedditCrawler
from src.crawlers.aihot_crawler import AIHotCrawler


@patch("src.crawlers.reddit_crawler.opencli_reddit_search")
def test_reddit_crawler_fetch(mock_opencli_search):
    mock_opencli_search.return_value = [
        {
            "title": "New breakthrough in LLM",
            "subreddit": "MachineLearning",
            "author": "ml_researcher",
            "score": 321,
            "comments": 42,
            "url": "https://www.reddit.com/r/MachineLearning/comments/abc/new_breakthrough_in_llm/",
        }
    ]

    crawler = RedditCrawler({
        "enabled": True,
        "subreddits": ["MachineLearning"],
        "sort": "hot",
        "limit": 10,
    })
    crawler.cache_ttl_seconds = None
    items = crawler.fetch()
    assert len(items) == 1
    assert items[0].source == "reddit"
    assert items[0].title == "New breakthrough in LLM"
    assert items[0].author == "ml_researcher"
    assert items[0].raw_data["reddit_score"] == 321
    mock_opencli_search.assert_called_once()


@patch("src.crawlers.reddit_crawler.opencli_reddit_search")
def test_reddit_crawler_search_queries_use_opencli(mock_opencli_search):
    mock_opencli_search.return_value = [
        {
            "title": "Open AI's Codex is going to kill Claude Code (finally)",
            "subreddit": "vibecoding",
            "author": "Conscious-Row-9936",
            "score": 42,
            "comments": 9,
            "url": "https://www.reddit.com/r/vibecoding/comments/1stkj5v/open_ais_codex_is_going_to_kill_claude_code/",
        }
    ]

    crawler = RedditCrawler(
        {
            "enabled": True,
            "subreddits": [],
            "search_queries": ["Codex"],
            "limit": 1,
            "max_age_hours": 72,
        }
    )
    crawler.cache_ttl_seconds = None

    items = crawler.fetch()

    assert len(items) == 1
    assert items[0].source == "reddit"
    assert items[0].title.startswith("Open AI's Codex")
    assert items[0].raw_data["subreddit"] == "vibecoding"
    mock_opencli_search.assert_called_once()


@patch("src.crawlers.aihot_crawler.requests.get")
def test_aihot_crawler_fetches_rss(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.text = """
    <rss><channel>
      <item>
        <title>Symphony为每个任务启动运行Codex智能体</title>
        <link>https://x.com/OpenAIDevs/status/2054252221941121035</link>
        <description>OpenAI Developers update</description>
        <pubDate>Fri, 15 May 2026 01:33:00 GMT</pubDate>
        <category>OpenAI</category>
      </item>
    </channel></rss>
    """

    crawler = AIHotCrawler({
        "feeds": ["https://aihot.virxact.com/feed.xml"],
        "max_results": 5,
        "max_age_hours": 48,
    })
    crawler.cache_ttl_seconds = None
    items = crawler.fetch()

    assert len(items) == 1
    assert items[0].source == "aihot"
    assert items[0].title == "Symphony为每个任务启动运行Codex智能体"
    assert "OpenAI" in items[0].tags
