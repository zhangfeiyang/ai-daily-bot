# src/crawlers/twitter_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import feedparser
import requests
from loguru import logger
from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class TwitterCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        instances = self.config.get("nitter_instances", ["https://nitter.net"])
        accounts = self.config.get("accounts", [])
        limit = self.config.get("limit", 20)

        items = []
        for account in accounts:
            rss_url = f"{self._pick_instance(instances)}/{account}/rss"
            try:
                resp = requests.get(rss_url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning(f"Twitter: failed to fetch @{account}: {e}")
                continue

            feed = feedparser.parse(resp.text)
            for entry in feed.get("entries", [])[:limit]:
                try:
                    pub_date = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    pub_date = datetime.now(timezone.utc)

                items.append(NewsItem(
                    source="twitter",
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    content=entry.get("summary", ""),
                    author=entry.get("author", account),
                    published_at=pub_date,
                    tags=["twitter"],
                    raw_data={"account": account},
                ))
        return items

    def _pick_instance(self, instances: list[str]) -> str:
        return instances[0] if instances else "https://nitter.net"
