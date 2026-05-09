from src.crawlers.github_crawler import GitHubCrawler
from src.crawlers.arxiv_crawler import ArxivCrawler
from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import main


def test_build_live_crawlers_defaults_to_github_only(monkeypatch):
    monkeypatch.delenv("DAILY_LIVE_INCLUDE_ARXIV", raising=False)

    sources_config = {
        "github": {"enabled": True},
        "arxiv": {"enabled": True},
    }

    crawlers = main.build_live_crawlers(sources_config)

    assert len(crawlers) == 1
    assert isinstance(crawlers[0], GitHubCrawler)


def test_build_live_crawlers_can_include_arxiv(monkeypatch):
    monkeypatch.setenv("DAILY_LIVE_INCLUDE_ARXIV", "1")

    sources_config = {
        "github": {"enabled": True},
        "arxiv": {"enabled": True},
    }

    crawlers = main.build_live_crawlers(sources_config)

    assert len(crawlers) == 2
    assert isinstance(crawlers[0], GitHubCrawler)
    assert isinstance(crawlers[1], ArxivCrawler)


def test_upload_feature_drafts_uses_today_staged_articles(tmp_path, monkeypatch):
    beijing_tz = timezone(timedelta(hours=8))
    today = datetime.now(beijing_tz).strftime("%Y-%m-%d")

    article_dir = tmp_path / "output" / "articles"
    article_dir.mkdir(parents=True)
    (article_dir / f"feature_{today}_1.html").write_text(
        "<!-- ARTICLE_TITLE: Draft One --><!-- THUMB_MEDIA_ID: thumb_1 --><p>One</p>",
        encoding="utf-8",
    )
    (article_dir / f"feature_{today}_2.html").write_text(
        "<!-- ARTICLE_TITLE: Draft Two --><p>Two</p>",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    publisher = MagicMock()
    publisher.create_draft.side_effect = ["media_1", "media_2"]

    assert main._upload_feature_drafts(publisher) is True
    assert publisher.create_draft.call_count == 2
    assert publisher.create_draft.call_args_list[0].kwargs["title"] == "Draft One"
    assert publisher.create_draft.call_args_list[0].kwargs["thumb_media_id"] == "thumb_1"
    assert publisher.create_draft.call_args_list[1].kwargs["title"] == "Draft Two"
