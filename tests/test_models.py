# tests/test_models.py
from datetime import datetime, timezone
from src.models import NewsItem


def test_news_item_creation():
    item = NewsItem(
        source="arxiv",
        title="Test Paper",
        url="https://arxiv.org/abs/2401.00001",
        content="Abstract of the paper.",
        author="Author Name",
        published_at=datetime(2026, 4, 19, 8, 0, 0, tzinfo=timezone.utc),
        tags=["AI", "LLM"],
        raw_data={"id": "2401.00001"},
    )
    assert item.source == "arxiv"
    assert item.title == "Test Paper"
    assert "AI" in item.tags
    assert item.raw_data["id"] == "2401.00001"


def test_news_item_default_tags():
    item = NewsItem(
        source="reddit",
        title="Test",
        url="https://reddit.com/r/test/1",
        content="content",
        author="user",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={},
    )
    assert item.tags == []
