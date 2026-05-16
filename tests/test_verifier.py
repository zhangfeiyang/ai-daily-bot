from unittest.mock import MagicMock, patch

from src.verifier import NewsVerifier


def test_web_search_merges_minimax_results():
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fddg">DDG Result</a>
        <a class="result__snippet">duck snippet</a>
      </div>
    </body></html>
    """

    response = MagicMock()
    response.status_code = 200
    response.text = html

    with patch("src.verifier.NewsVerifier._opencli_web_search", return_value=[]), patch("requests.post", return_value=response), patch(
        "src.verifier.NewsVerifier._minimax_web_search",
        return_value=[
            {
                "title": "MiniMax Result",
                "url": "https://example.com/minimax",
                "snippet": "minimax snippet",
                "date": "",
            }
        ],
    ):
        results = NewsVerifier._web_search("test query", max_results=3, use_minimax=True)

    urls = [r["url"] for r in results]
    assert "https://example.com/ddg" in urls
    assert "https://example.com/minimax" in urls


def test_web_search_prefers_opencli_google_results():
    with patch(
        "src.verifier.NewsVerifier._opencli_web_search",
        return_value=[
            {
                "title": "OpenCLI Result",
                "url": "https://example.com/opencli",
                "snippet": "opencli snippet",
                "date": "",
            }
        ],
    ), patch(
        "src.verifier.NewsVerifier._minimax_web_search",
        return_value=[],
    ), patch(
        "requests.post",
    ) as mock_post:
        results = NewsVerifier._web_search("test query", max_results=3)

    assert results[0]["url"] == "https://example.com/opencli"
    mock_post.assert_not_called()


def test_search_twitter_account_prefers_opencli_twitter():
    verifier = NewsVerifier(MagicMock(), {})
    item = MagicMock()
    item.title = "OpenAI ships Codex in ChatGPT mobile app"
    item.content = "Some content about Codex"
    item.source = "news"

    with patch.object(
        NewsVerifier,
        "_opencli_twitter_search",
        return_value=[
            {
                "url": "https://x.com/OpenAI/status/2055016850849993072",
                "title": "OpenAI",
                "snippet": "Codex in the ChatGPT mobile app",
                "date": "2026-05-14",
            }
        ],
    ) as mock_opencli, patch.object(
        NewsVerifier,
        "_web_search",
        return_value=[],
    ) as mock_web:
        result = verifier._search_twitter_account(item, "openai", "OpenAI", "official_twitter")

    assert result["verified"] is True
    assert result["official_url"] == "https://x.com/OpenAI/status/2055016850849993072"
    mock_opencli.assert_called_once()
    mock_web.assert_not_called()
