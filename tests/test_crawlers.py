# tests/test_crawlers.py
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.crawlers.base import BaseCrawler
from src.crawlers.arxiv_crawler import ArxivCrawler
from src.models import NewsItem


class DummyCrawler(BaseCrawler):
    def fetch(self):
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
    items = crawler.fetch()
    assert len(items) == 1
    assert items[0].source == "arxiv"
