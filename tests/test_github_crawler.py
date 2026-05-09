from unittest.mock import MagicMock, patch

from src.crawlers.github_crawler import GitHubCrawler


@patch("src.crawlers.github_crawler.requests.get")
def test_github_crawler_honors_topic_limit(mock_get):
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

    items = crawler.fetch()

    assert len(items) == 2
    assert mock_get.call_count == 2
