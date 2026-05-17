from unittest.mock import patch

from src.utils import opencli_search


def test_web_search_falls_back_when_google_blocked(monkeypatch):
    monkeypatch.delenv("OPENCLI_WEB_SEARCH_PROVIDERS", raising=False)

    def fake_provider(provider, query, limit=5, timeout=180):
        if provider == "google":
            return []
        if provider == "duckduckgo":
            return [{"title": "DDG", "url": "https://example.com/ddg", "snippet": "ok"}]
        return []

    with patch.object(opencli_search, "provider_search", side_effect=fake_provider) as mock_search:
        results = opencli_search.web_search("test query", limit=3)

    assert results[0]["url"] == "https://example.com/ddg"
    assert [call.args[0] for call in mock_search.call_args_list] == ["google", "duckduckgo"]


def test_web_search_maps_bing_to_yahoo(monkeypatch):
    monkeypatch.setenv("OPENCLI_WEB_SEARCH_PROVIDERS", "bing")

    with patch.object(
        opencli_search,
        "provider_search",
        return_value=[{"title": "Yahoo", "url": "https://example.com/yahoo"}],
    ) as mock_search:
        results = opencli_search.web_search("test query", limit=3)

    assert results[0]["url"] == "https://example.com/yahoo"
    assert mock_search.call_args.args[0] == "yahoo"


def test_reddit_search_passes_time_and_sort_filters():
    with patch.object(opencli_search, "_run_opencli_search", return_value=[]) as mock_run:
        opencli_search.reddit_search("OpenAI Codex", limit=7, time_filter="day", sort="top")

    assert mock_run.call_args.args[0] == [
        "reddit",
        "search",
        "OpenAI Codex",
        "--limit",
        "7",
        "--time",
        "day",
        "--sort",
        "top",
    ]
