# src/crawlers/reddit_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class RedditCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        subreddits = self.config.get("subreddits", ["MachineLearning"])
        sort = self.config.get("sort", "hot")
        limit = self.config.get("limit", 15)

        items = []
        for sub_name in subreddits:
            url = f"https://www.reddit.com/r/{sub_name}/{sort}/.rss?limit={limit}"
            try:
                resp = requests.get(url, headers={"User-Agent": "ai-news-bot/1.0"}, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning(f"Reddit: failed to fetch r/{sub_name}: {e}")
                continue

            feed = feedparser.parse(resp.text)
            for entry in feed.get("entries", [])[:limit]:
                title = entry.get("title", "")
                # Skip stickied posts (usually subreddit rules)
                if any(kw in title.lower() for kw in ["megathread", "weekly thread", "rules"]):
                    continue

                link = entry.get("link", "")
                content = entry.get("summary", title)
                # Strip HTML from summary
                import re
                content = re.sub(r"<[^>]+>", "", content)[:2000]

                author = entry.get("author", "")
                # Reddit RSS author format: "/u/username"
                if author.startswith("/u/"):
                    author = author[3:]

                try:
                    pub_date = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    pub_date = datetime.now(timezone.utc)

                # Extract flair from tags
                tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]

                # Extract image URL from summary or media_content
                import html as html_lib
                image_url = ""
                media = entry.get("media_content", [])
                for m in media:
                    if m.get("medium") == "image" or m.get("type", "").startswith("image"):
                        image_url = html_lib.unescape(m.get("url", ""))
                        break
                if not image_url:
                    img_match = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
                    if img_match:
                        image_url = html_lib.unescape(img_match.group(1))

                items.append(NewsItem(
                    source="reddit",
                    title=title,
                    url=link,
                    content=content,
                    author=author,
                    published_at=pub_date,
                    tags=tags,
                    raw_data={"subreddit": sub_name, "image_url": image_url},
                ))

        return self.filter_recent(items)
