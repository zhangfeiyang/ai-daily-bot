from unittest.mock import MagicMock, patch

from src.crawlers.github_crawler import GitHubCrawler


@patch("src.crawlers.github_crawler.requests.get")
@patch("src.crawlers.github_crawler.opencli_google_search", return_value=[])
def test_github_crawler_honors_topic_limit(mock_opencli_search, mock_get):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "items": [
            {
                "full_name": "owner/repo",
                "stargazers_count": 123,
                "description": "A useful AI repository",
                "html_url": "https://github.com/owner/repo",
                "language": "Python",
                "topics": ["llm"],
            }
        ]
    }
    mock_get.return_value = response

    crawler = GitHubCrawler(
        {
            "topics": ["llm", "mcp", "rag", "robotics"],
            "topic_limit": 2,
            "languages": ["python"],
            "min_stars": 50,
            "max_results": 10,
            "max_age_hours": 96,
        }
    )
    crawler.cache_ttl_seconds = None

    items = crawler.fetch()

    assert len(items) == 2
    assert mock_get.call_count == 2
    mock_opencli_search.assert_called()


@patch("src.crawlers.github_crawler.opencli_google_search")
@patch("src.crawlers.github_crawler.requests.get")
def test_github_crawler_prefers_opencli_search(mock_get, mock_opencli_search):
    mock_opencli_search.return_value = [
        {"url": "https://github.com/openai/codex", "title": "openai/codex", "snippet": "Codex"}
    ]

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "full_name": "openai/codex",
        "stargazers_count": 5000,
        "description": "Lightweight coding agent that runs locally",
        "html_url": "https://github.com/openai/codex",
        "language": "Python",
        "topics": ["llm"],
        "created_at": "2026-05-15T00:00:00Z",
    }
    mock_get.return_value = response

    crawler = GitHubCrawler(
        {
            "topics": ["codex"],
            "topic_limit": 1,
            "languages": ["python"],
            "min_stars": 50,
            "max_results": 10,
            "max_age_hours": 96,
        }
    )
    crawler.cache_ttl_seconds = None

    items = crawler.fetch()

    assert len(items) == 1
    assert items[0].source == "github"
    assert items[0].url == "https://github.com/openai/codex"
    mock_opencli_search.assert_called_once()
