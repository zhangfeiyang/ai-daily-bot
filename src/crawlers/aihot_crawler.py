# src/crawlers/aihot_crawler.py
from datetime import datetime, timezone
import re

import feedparser
from bs4 import BeautifulSoup
from loguru import logger
import requests

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class AIHotCrawler(BaseCrawler):
    """Fetch curated AI items from AIHOT RSS feeds."""

    def _fetch(self) -> list[NewsItem]:
        feeds = self.config.get("feeds") or [
            "https://aihot.virxact.com/feed.xml",
            "https://aihot.virxact.com/feed/all.xml",
        ]
        max_results = self.config.get("max_results", 30)
        items: list[NewsItem] = []
        seen_urls: set[str] = set()

        for feed_url in feeds:
            try:
                resp = requests.get(
                    feed_url,
                    timeout=self.config.get("timeout", 20),
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
                )
                resp.raise_for_status()
                parsed = feedparser.parse(resp.text)
            except Exception as e:
                logger.warning(f"AIHOT feed failed: {feed_url}: {e}")
                continue

            for entry in parsed.get("entries", []):
                item = self._parse_entry(entry, feed_url)
                if not item or item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                items.append(item)

        items = self.filter_recent(items)
        return items[:max_results]

    def _parse_entry(self, entry: dict, feed_url: str) -> NewsItem | None:
        title = self._clean_text(entry.get("title", ""))
        url = entry.get("link", "")
        if not title or not url:
            return None

        summary_html = entry.get("summary", "") or entry.get("description", "")
        summary = self._clean_text(BeautifulSoup(summary_html, "html.parser").get_text(" ", strip=True))
        published_at = self._parse_entry_date(entry)
        tags = ["aihot"]
        for tag in entry.get("tags", []) or []:
            term = tag.get("term") if isinstance(tag, dict) else getattr(tag, "term", "")
            if term:
                tags.append(str(term))

        return NewsItem(
            source="aihot",
            title=title,
            url=url,
            content=summary,
            author=entry.get("author", "AIHOT") or "AIHOT",
            published_at=published_at,
            tags=tags,
            raw_data={
                "feed_url": feed_url,
                "summary_html": summary_html,
                "links": [url],
            },
        )

    @staticmethod
    def _parse_entry_date(entry: dict) -> datetime:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        for key in ("published", "updated"):
            value = entry.get(key, "")
            if not value:
                continue
            try:
                from email.utils import parsedate_to_datetime

                dt = parsedate_to_datetime(value)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        return datetime.now(timezone.utc)

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text or "")
        return text.strip()
