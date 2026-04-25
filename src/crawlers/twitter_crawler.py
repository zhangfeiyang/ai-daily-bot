# src/crawlers/twitter_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote
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
        "人工智能", "大模型", "深度学习", "机器学习", "神经网络",
        "智能体", "开源模型", "推理", "训练",
    ]

    # 泛娱乐等话题关键词，用于排除
    EXCLUDE_KEYWORDS = [
        "football", "nba", "soccer", "game today", "box office",
        "movie review", "celebrity", "gossip", "recipe", "cooking",
        "travel vlog", "music video", "concert", "fashion",
        "fantasy football", "super bowl", "playoff",
    ]

    def fetch(self) -> list[NewsItem]:
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
                    pub_date = datetime.now(timezone.utc)

                author = entry.get("author", account)
                if author.startswith("/u/"):
                    author = author[3:]
                if author.startswith("@"):
                    author = author[1:]

                url = entry.get("link", "")
                url = re.sub(r"https?://[^/]+", "https://x.com", url)

                image_url = ""
                img_match = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
                if img_match:
                    image_url = img_match.group(1)
                    # Nitter returns encoded URLs like /pic/media%2Fxxx.jpg
                    # Decode and rebuild proper Twitter image URL
                    image_url = unquote(image_url)
                    image_url = re.sub(r"https?://[^/]+/pic/", "https://pbs.twimg.com/", image_url)

                items.append(NewsItem(
                    source="twitter",
                    title=title,
                    url=url,
                    content=summary_text[:2000],
                    author=author,
                    published_at=pub_date,
                    tags=["twitter"],
                    raw_data={"account": account, "image_url": image_url},
                ))

        return self.filter_recent(items)

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
