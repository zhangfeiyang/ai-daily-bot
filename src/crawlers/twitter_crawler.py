# src/crawlers/twitter_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlparse
import re
import html as html_lib

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
    # AI 相关关键词，用于过滤非 AI 内容
    AI_KEYWORDS = [
        "ai", "artificial intelligence", "machine learning", "deep learning",
        "neural", "llm", "gpt", "transformer", "model", "agi",
        "chatgpt", "claude", "gemini", "openai", "anthropic",
        "diffusion", "rlhf", "fine-tun", "inference", "training",
        "nlp", "computer vision", "robot", "autonomous",
        "hugging face", "pytorch", "tensorflow", "cuda", "gpu",
        "reasoning", "embedding", "token", "benchmark", "sota",
        "multimodal", "generation", "classifier", "tokenizer",
        "agent", "multi-agent", "agentic", "copilot", "autonomous agent",
        "claude code", "codex", "openclass", "openclaw", "cursor", "windsurf",
        "devin", "manus", "crewai", "langchain", "auto-gpt",
        "coding assistant", "code generation", "ai tool", "mcp",
        "人工智能", "大模型", "深度学习", "机器学习", "神经网络",
        "智能体", "开源模型", "推理", "训练", "AI工具", "编程助手",
    ]

    # 泛娱乐等话题关键词，用于排除
    EXCLUDE_KEYWORDS = [
        "football", "nba", "soccer", "game today", "box office",
        "movie review", "celebrity", "gossip", "recipe", "cooking",
        "travel vlog", "music video", "concert", "fashion",
        "fantasy football", "super bowl", "playoff",
    ]

    def _fetch(self) -> list[NewsItem]:
        instances = self.config.get("nitter_instances", DEFAULT_INSTANCES)
        accounts = self.config.get("accounts", [])
        limit = self.config.get("limit", 20)
        filter_ai = self.config.get("filter_ai_only", False)

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
                if not title or "whitelisted" in title.lower():
                    continue

                summary = entry.get("summary", "")
                summary_text = re.sub(r"<[^>]+>", "", summary)

                # AI content filter
                if filter_ai and not self._is_ai_related(title + " " + summary_text):
                    continue

                try:
                    pub_date = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    # Try ISO 8601 format
                    try:
                        pub_date = datetime.fromisoformat(entry.get("published", "").replace("Z", "+00:00"))
                    except Exception:
                        pub_date = datetime.now(timezone.utc)

                author = entry.get("author", account)
                if author.startswith("/u/"):
                    author = author[3:]
                if author.startswith("@"):
                    author = author[1:]

                url = entry.get("link", "")
                url = re.sub(r"https?://[^/]+", "https://x.com", url)

                summary_html = entry.get("summary", "")

                links = []
                for href in re.findall(r'<a[^>]+href="([^"]+)"', summary_html):
                    link = html_lib.unescape(href)
                    if link.startswith("/"):
                        link = urljoin(instance, link)
                    if self._is_nitter_url(link):
                        link = re.sub(r"https?://[^/]+", "https://x.com", link)
                    if link.startswith("http") and link not in links:
                        links.append(link)

                image_urls = []
                for img_match in re.finditer(r'<img[^>]+src="([^"]+)"', summary_html):
                    img_url = self._normalize_nitter_media_url(img_match.group(1), instance)
                    if img_url and img_url not in image_urls:
                        image_urls.append(img_url)

                video_urls = []
                for src in re.findall(r'<(?:source|video)[^>]+src="([^"]+)"', summary_html):
                    video_url = self._normalize_nitter_media_url(src, instance)
                    if video_url and video_url not in video_urls:
                        video_urls.append(video_url)
                for href in re.findall(r'href="([^"]+\.(?:mp4|m3u8)[^"]*)"', summary_html, flags=re.I):
                    video_url = self._normalize_nitter_media_url(href, instance)
                    if video_url and video_url not in video_urls:
                        video_urls.append(video_url)

                raw = {"account": account, "image_url": image_urls[0] if image_urls else ""}
                if len(image_urls) > 1:
                    raw["image_urls"] = image_urls
                if video_urls:
                    raw["video_url"] = video_urls[0]
                    raw["video_urls"] = video_urls
                if links:
                    raw["links"] = links

                items.append(NewsItem(
                    source="twitter",
                    title=title,
                    url=url,
                    content=summary_text[:2000],
                    author=author,
                    published_at=pub_date,
                    tags=["twitter"],
                    raw_data=raw,
                ))

        return self.filter_recent(items)

    @staticmethod
    def fetch_top_comments(
        tweet_url: str,
        account: str = "",
        limit: int = 20,
        instances: list[str] | None = None,
    ) -> list[dict]:
        """Fetch top replies/comments for a tweet from Nitter/XCancel mirrors.

        The parser is intentionally heuristic: when like/reply counters are not
        exposed by the mirror, it still keeps media-rich replies and official
        author replies near the top.
        """
        status_info = TwitterCrawler._extract_status_info(tweet_url)
        if not status_info:
            return []

        username, status_id = status_info
        candidates = instances or DEFAULT_INSTANCES

        for instance in candidates:
            try:
                status_page = f"{instance}/{username}/status/{status_id}"
                resp = requests.get(
                    status_page,
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
                )
                if resp.status_code != 200 or not resp.text.strip():
                    continue

                comments = TwitterCrawler._parse_status_comments(
                    resp.text,
                    instance=instance,
                    main_author=account or username,
                    limit=limit,
                )
                if comments:
                    logger.debug(
                        f"Twitter: fetched {len(comments)} comments for @{username} from {instance}"
                    )
                    return comments
            except Exception as e:
                logger.debug(f"Twitter: comment fetch failed via {instance}: {e}")
                continue

        return []

    @staticmethod
    def _normalize_nitter_media_url(media_url: str, instance: str) -> str:
        media_url = html_lib.unescape(unquote(media_url or ""))
        if not media_url:
            return ""
        if media_url.startswith("/"):
            media_url = urljoin(instance, media_url)

        parsed = re.search(r"https?://[^/]+/pic/(?:orig/)?(.+)$", media_url)
        if parsed:
            path = parsed.group(1)
            if path.startswith("media/"):
                return f"https://pbs.twimg.com/{path}"
            if path.startswith("ext_tw_video_thumb/"):
                return f"https://pbs.twimg.com/{path}"
            if path.startswith("amplify_video_thumb/"):
                return f"https://pbs.twimg.com/{path}"
            return f"https://pbs.twimg.com/{path}"

        media_url = re.sub(r"https?://[^/]+/pic/", "https://pbs.twimg.com/", media_url)
        return media_url

    @staticmethod
    def _extract_status_info(tweet_url: str) -> tuple[str, str] | None:
        if not tweet_url:
            return None
        match = re.search(r"x\.com/([^/?#]+)/status/(\d+)", tweet_url)
        if match:
            return match.group(1), match.group(2)
        match = re.search(r"twitter\.com/([^/?#]+)/status/(\d+)", tweet_url)
        if match:
            return match.group(1), match.group(2)
        match = re.search(r"/([^/?#]+)/status/(\d+)", tweet_url)
        if match:
            return match.group(1), match.group(2)
        return None

    @staticmethod
    def _parse_status_comments(
        html: str,
        instance: str,
        main_author: str = "",
        limit: int = 20,
    ) -> list[dict]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        timeline_items = soup.select(".timeline-item")
        if not timeline_items:
            return []

        main_author = (main_author or "").lstrip("@").lower()
        comments = []

        for node in timeline_items[1:]:
            text_node = node.select_one(".tweet-content") or node.select_one(".content")
            text = text_node.get_text(" ", strip=True) if text_node else ""
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue

            author = TwitterCrawler._extract_comment_author(node)
            images = TwitterCrawler._extract_comment_images(node, instance)
            video_urls = TwitterCrawler._extract_comment_videos(node, instance)
            likes = TwitterCrawler._extract_comment_metric(node, {"heart", "like"})
            replies = TwitterCrawler._extract_comment_metric(node, {"comment", "reply"})
            comment_url = TwitterCrawler._extract_comment_url(node, instance)

            comments.append({
                "author": author,
                "text": text[:1000],
                "url": comment_url,
                "likes": likes,
                "replies": replies,
                "images": images,
                "video_urls": video_urls,
                "is_main_author": bool(author and author.lower().lstrip("@") == main_author),
            })

        if not comments:
            return []

        comments.sort(
            key=lambda c: (
                c.get("is_main_author", False),
                c.get("likes", 0),
                c.get("replies", 0),
                len(c.get("images", [])) > 0,
                len(c.get("text", "")),
            ),
            reverse=True,
        )
        return comments[:limit]

    @staticmethod
    def _extract_comment_author(node) -> str:
        author = ""
        for selector in ("a.username", "a.fullname", "span.username"):
            el = node.select_one(selector)
            if el:
                text = el.get_text(" ", strip=True)
                if text:
                    author = text
                    break
        if not author:
            for a in node.find_all("a", href=True):
                href = a.get("href", "")
                if "/status/" in href or href.startswith("/search"):
                    continue
                text = a.get_text(" ", strip=True)
                if text.startswith("@") or href.startswith("/"):
                    author = text or href.strip("/")
                    break
        return author.strip()

    @staticmethod
    def _extract_comment_url(node, instance: str) -> str:
        for selector in ("a.tweet-link", "a.tweet-date", "a[href*='/status/']"):
            el = node.select_one(selector)
            if el and el.get("href"):
                href = html_lib.unescape(el["href"])
                if href.startswith("/"):
                    href = urljoin(instance, href)
                return href
        return ""

    @staticmethod
    def _extract_comment_images(node, instance: str) -> list[str]:
        images = []
        for img in node.find_all("img"):
            src = img.get("src", "")
            alt = (img.get("alt", "") or "").lower()
            if not src:
                continue
            if any(skip in (src + alt).lower() for skip in ("avatar", "profile", "logo", "icon", "badge", "1x1", "pixel")):
                continue
            src = TwitterCrawler._normalize_nitter_media_url(src, instance)
            if src and src not in images:
                images.append(src)
        return images

    @staticmethod
    def _extract_comment_videos(node, instance: str) -> list[str]:
        videos = []
        for tag in node.find_all(["video", "source"]):
            src = tag.get("src", "")
            if src:
                src = TwitterCrawler._normalize_nitter_media_url(src, instance)
                if src and src not in videos:
                    videos.append(src)
        for href in re.findall(r'href="([^"]+\.(?:mp4|m3u8)[^"]*)"', str(node), flags=re.I):
            src = TwitterCrawler._normalize_nitter_media_url(href, instance)
            if src and src not in videos:
                videos.append(src)
        return videos

    @staticmethod
    def _extract_comment_metric(node, keywords: set[str]) -> int:
        text = " ".join(node.stripped_strings)
        numbers = [int(n) for n in re.findall(r"\b(\d[\d,]*)\b", text.replace(",", ""))]
        if not numbers:
            return 0
        # Mirrors do not always label metrics clearly; use the largest visible count
        # as a weak signal only.
        return max(numbers)

    @staticmethod
    def _is_nitter_url(url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return any(name in host for name in ("nitter", "xcancel"))

    def _is_ai_related(self, text: str) -> bool:
        """Check if tweet content is AI-related."""
        text_lower = text.lower()
        # Exclude non-AI topics first
        for kw in self.EXCLUDE_KEYWORDS:
            if kw in text_lower:
                return False
        # Check for AI keywords
        return any(kw in text_lower for kw in self.AI_KEYWORDS)

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
