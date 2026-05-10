# src/crawlers/reddit_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

import feedparser
import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class RedditCrawler(BaseCrawler):
    # Low-quality keywords that indicate low-engagement / meta posts
    LOW_QUALITY_KEYWORDS = [
        "hiring", "self-promotion", "weekly thread", "rules", "megathread",
        "career", "interview", "resume", "salary", "negotiation",
        "desk-rejected", "reviewers", "proceedings missing",
        "how do i", "what is", "help with", "question about",
        "looking for", "anyone know", "is it worth", "should i",
        "advice needed", "need help", "newbie", "beginner",
    ]

    # High-quality indicators (research/code releases get these flairs/tags)
    HIGH_QUALITY_INDICATORS = [
        "[r]", "[research]", "[p]", "[project]",
        "paper", "github", "release", "open source",
    ]

    def fetch(self) -> list[NewsItem]:
        subreddits = self.config.get("subreddits", ["MachineLearning"])
        sort = self.config.get("sort", "hot")
        limit = self.config.get("limit", 15)
        # Minimum score threshold (upvotes) for a post to be included
        min_score = self.config.get("min_score", 20)

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

                # Fetch post score via Reddit JSON API
                score = self._fetch_post_score(link)
                if score is not None and score < min_score:
                    logger.debug(f"Reddit: skipping low-score post ({score} < {min_score}): {title[:50]}...")
                    continue

                # Fallback: heuristic filtering when score is unavailable
                if score is None:
                    quality = self._assess_post_quality(title, entry)
                    if quality == "low":
                        logger.debug(f"Reddit: skipping low-quality post: {title[:50]}...")
                        continue

                content = entry.get("summary", title)
                # Strip HTML from summary
                content = re.sub(r"<[^>]+>", "", content)[:2000]

                author = entry.get("author", "")
                # Reddit RSS author format: "/u/username"
                if author.startswith("/u/"):
                    author = author[3:]

                try:
                    pub_date = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    # Try ISO 8601 format (Reddit uses this)
                    try:
                        pub_date = datetime.fromisoformat(entry.get("published", ""))
                    except Exception:
                        pub_date = datetime.now(timezone.utc)

                # Extract flair from tags
                tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]

                # Extract image URL from summary or media_content
                import html as html_lib
                image_url = ""
                video_url = ""
                media = entry.get("media_content", [])
                for m in media:
                    if m.get("medium") == "image" or m.get("type", "").startswith("image"):
                        image_url = html_lib.unescape(m.get("url", ""))
                        break
                    if m.get("medium") == "video" or m.get("type", "").startswith("video"):
                        video_url = html_lib.unescape(m.get("url", ""))
                if not image_url:
                    img_match = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
                    if img_match:
                        image_url = html_lib.unescape(img_match.group(1))

                # Extract video URL from summary (v.redd.it links)
                if not video_url:
                    video_match = re.search(r'(https?://v\.redd\.it/[a-zA-Z0-9]+)', entry.get("summary", ""))
                    if video_match:
                        video_url = video_match.group(1)

                # Extract external links from summary (links to original articles)
                links = []
                for href in re.findall(r'<a[^>]+href="([^"]+)"', entry.get("summary", "")):
                    href = html_lib.unescape(href)
                    # Skip Reddit internal links and image/video links
                    if href.startswith("https://www.reddit.com") or href.startswith("/r/"):
                        continue
                    if any(ext in href.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", ".mp4", ".webm"]):
                        continue
                    if href not in links:
                        links.append(href)

                items.append(NewsItem(
                    source="reddit",
                    title=title,
                    url=link,
                    content=content,
                    author=author,
                    published_at=pub_date,
                    tags=tags,
                    raw_data={
                        "subreddit": sub_name,
                        "image_url": image_url,
                        "video_url": video_url,
                        "links": links[:5],
                        "reddit_score": score,
                    },
                ))

        return self.filter_recent(items)

    def _assess_post_quality(self, title: str, entry) -> str:
        """Heuristic quality assessment when Reddit API score is unavailable.

        Returns: 'high', 'medium', or 'low'
        """
        title_lower = title.lower()
        content = entry.get("summary", "").lower()

        # Check low-quality keywords
        for kw in self.LOW_QUALITY_KEYWORDS:
            if kw in title_lower:
                return "low"

        # Check high-quality indicators
        for indicator in self.HIGH_QUALITY_INDICATORS:
            if indicator in title_lower:
                return "high"

        # Posts with external links are more likely to be news
        external_links = re.findall(r'href="(https?://[^"]+)"', entry.get("summary", ""))
        external_links = [l for l in external_links if not l.startswith("https://www.reddit.com")]
        if external_links:
            return "high"

        # Default: medium (let downstream pipeline decide)
        return "medium"

    def _fetch_post_score(self, post_url: str) -> int | None:
        """Fetch post score (upvotes) via Reddit JSON API.

        Reddit provides JSON data for any page by appending .json to the URL.
        Returns None if the request fails.
        """
        if not post_url:
            return None

        # Ensure URL ends without trailing slash before adding .json
        json_url = post_url.rstrip("/") + ".json"
        try:
            resp = requests.get(
                json_url,
                headers={"User-Agent": "ai-news-bot/1.0"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            # Reddit JSON structure: [post_data, comments_data]
            # post_data[0]["data"]["children"][0]["data"]["score"]
            if isinstance(data, list) and len(data) > 0:
                post_list = data[0].get("data", {}).get("children", [])
                if post_list:
                    return post_list[0].get("data", {}).get("score")
            return None
        except Exception as e:
            logger.debug(f"Reddit: failed to fetch score for {post_url[:50]}...: {e}")
            return None
