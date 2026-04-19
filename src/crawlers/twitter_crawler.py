# src/crawlers/twitter_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

import feedparser
import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem

DEFAULT_INSTANCES = [
    "https://nitter.net",
    "https://xcancel.com",
    "https://nitter.cz",
    "https://nitter.poast.org",
]


class TwitterCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        instances = self.config.get("nitter_instances", DEFAULT_INSTANCES)
        accounts = self.config.get("accounts", [])
        limit = self.config.get("limit", 20)

        # Find a working instance
        instance = self._find_working_instance(instances)
        if not instance:
            logger.error("Twitter: no working Nitter instance found")
            return []

        items = []
        for account in accounts:
            rss_url = f"{instance}/{account}/rss"
            try:
                resp = requests.get(
                    rss_url,
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning(f"Twitter: failed to fetch @{account}: {e}")
                continue

            feed = feedparser.parse(resp.text)
            for entry in feed.get("entries", [])[:limit]:
                title = entry.get("title", "")
                # Skip empty or error entries
                if not title or "whitelisted" in title.lower():
                    continue

                # Strip HTML from summary
                summary = entry.get("summary", "")
                summary = re.sub(r"<[^>]+>", "", summary)

                try:
                    pub_date = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    pub_date = datetime.now(timezone.utc)

                author = entry.get("author", account)
                if author.startswith("/u/"):
                    author = author[3:]
                if author.startswith("@"):
                    author = author[1:]

                items.append(NewsItem(
                    source="twitter",
                    title=title,
                    url=entry.get("link", ""),
                    content=summary[:2000],
                    author=author,
                    published_at=pub_date,
                    tags=["twitter"],
                    raw_data={"account": account},
                ))

        return items

    def _find_working_instance(self, instances: list[str]) -> str:
        """测试并返回第一个可用的 Nitter 实例。"""
        for inst in instances:
            try:
                resp = requests.get(
                    f"{inst}/OpenAI/rss",
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
                )
                if resp.status_code == 200 and "<rss" in resp.text[:500].lower():
                    entries = feedparser.parse(resp.text).get("entries", [])
                    if entries:
                        logger.info(f"Twitter: using instance {inst}")
                        return inst
            except Exception:
                continue
        return ""
