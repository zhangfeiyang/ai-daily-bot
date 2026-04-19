# tests/test_twitter_crawler.py
from unittest.mock import patch, MagicMock
from src.crawlers.twitter_crawler import TwitterCrawler


@patch("src.crawlers.twitter_crawler.feedparser")
@patch("src.crawlers.twitter_crawler.requests.get")
def test_twitter_crawler_fetch(mock_get, mock_feedparser):
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = "<rss>fake rss</rss>"
    mock_get.return_value.raise_for_status = MagicMock()

    mock_feedparser.parse.return_value = {
        "entries": [
            {
                "title": "Exciting AI update from OpenAI!",
                "link": "https://nitter.net/OpenAI/status/123",
                "summary": "We are releasing a new model...",
                "author": "@OpenAI",
                "published": "Fri, 18 Apr 2026 12:00:00 GMT",
            }
        ]
    }

    crawler = TwitterCrawler({
        "enabled": True,
        "nitter_instances": ["https://nitter.net"],
        "accounts": ["OpenAI"],
        "limit": 10,
    })
    items = crawler.fetch()
    assert len(items) >= 1
    assert items[0].source == "twitter"
    assert items[0].title == "Exciting AI update from OpenAI!"
