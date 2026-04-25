# src/crawlers/china_ai_crawler.py
"""爬取国内 AI 公司最新动态。

通过国内 AI 科技媒体（机器之心、量子位、36氪）RSS/页面获取国内 AI 新闻。
"""

from datetime import datetime, timezone, timedelta
import re
import html as html_lib

import requests
from bs4 import BeautifulSoup
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem

# 国内 AI 新闻源
SOURCES = {
    "quantumbit": {
        "name": "量子位",
        "rss": "https://www.qbitai.com/feed",
        "base_url": "https://www.qbitai.com",
    },
    "zhidx": {
        "name": "智东西",
        "rss": "https://www.zhidx.com/rss",
        "base_url": "https://www.zhidx.com",
    },
    "leiphone": {
        "name": "雷锋网",
        "rss": "https://www.leiphone.com/feed",
        "base_url": "https://www.leiphone.com",
    },
}

# 国内 AI 公司关键词（用于过滤）
COMPANY_KEYWORDS = [
    "DeepSeek", "deepseek", "深度求索",
    "智谱", "zhipu", "ChatGLM", "GLM",
    "MiniMax", "minimax",
    "Kimi", "moonshot", "月之暗面",
    "小米", "xiaomi", "MiLM",
    "通义", "Qwen", "千问",
    "豆包", "doubao", "字节", "bytedance", "Cloudream",
    "百度", "Baidu", "文心", "ERNIE",
    "华为", "Huawei", "盘古", "昇腾",
    "商汤", "SenseTime",
]


class ChinaAICrawler(BaseCrawler):
    """爬取国内 AI 科技媒体的 RSS，过滤与国内 AI 公司相关的新闻。"""

    def fetch(self) -> list[NewsItem]:
        enabled_sources = self.config.get(
            "sources", list(SOURCES.keys())
        )
        max_age_hours = self.config.get("max_age_hours", 72)
        max_results = self.config.get("max_results", 20)
        # Whether to filter by company keywords; default True
        filter_companies = self.config.get("filter_companies", True)

        items = []
        for source_key in enabled_sources:
            if source_key not in SOURCES:
                continue
            source_cfg = SOURCES[source_key]
            try:
                source_items = self._fetch_rss(source_key, source_cfg, max_age_hours)
                if filter_companies:
                    source_items = self._filter_china_ai(source_items)
                items.extend(source_items)
                logger.debug(f"ChinaAI {source_cfg['name']}: {len(source_items)} items")
            except Exception as e:
                logger.warning(f"ChinaAI {source_cfg['name']} failed: {e}")

        return items[:max_results]

    def _fetch_rss(
        self,
        source_key: str,
        source_cfg: dict,
        max_age_hours: int,
    ) -> list[NewsItem]:
        """解析 RSS feed 获取新闻。"""
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        try:
            resp = requests.get(
                source_cfg["rss"],
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
            )
            if resp.status_code != 200:
                return items
        except Exception as e:
            logger.debug(f"RSS fetch failed for {source_cfg['name']}: {e}")
            return items

        from xml.etree import ElementTree as ET
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return items

        # RSS 2.0: <rss><channel><item>
        # Atom: <feed><entry>
        entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for entry in entries:
            title = self._get_text(entry, "title") or ""
            link = self._get_text(entry, "link") or ""
            description = self._get_text(entry, "description") or self._get_text(entry, "summary") or ""
            pub_date_str = self._get_text(entry, "pubDate") or self._get_text(entry, "published") or ""

            if not title or not link:
                continue

            # Clean description HTML
            desc_clean = BeautifulSoup(description, "html.parser").get_text(strip=True)

            # Parse date
            pub_date = self._parse_rss_date(pub_date_str)
            if pub_date and pub_date < cutoff:
                continue

            # Extract image from description
            image_url = ""
            desc_soup = BeautifulSoup(description, "html.parser")
            img = desc_soup.find("img")
            if img and img.get("src"):
                image_url = img["src"]

            # Also check media:content
            media = entry.find("{http://search.yahoo.com/mrss/}content")
            if media is not None and media.get("url"):
                image_url = media.get("url")

            # Handle relative links
            if link.startswith("/"):
                link = source_cfg["base_url"] + link
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif image_url.startswith("/"):
                image_url = source_cfg["base_url"] + image_url

            item = NewsItem(
                source=source_key,
                title=html_lib.unescape(title),
                url=html_lib.unescape(link),
                content=desc_clean[:2000],
                author=source_cfg["name"],
                published_at=pub_date or datetime.now(timezone.utc),
                tags=["china-ai", source_cfg["name"]],
                raw_data={"image_url": image_url} if image_url else {},
            )
            items.append(item)

        return items

    def _filter_china_ai(self, items: list[NewsItem]) -> list[NewsItem]:
        """过滤出与国内 AI 公司相关的新闻。"""
        filtered = []
        for item in items:
            text = (item.title + " " + item.content).lower()
            if any(kw.lower() in text for kw in COMPANY_KEYWORDS):
                filtered.append(item)
        return filtered

    @staticmethod
    def _get_text(element, tag: str) -> str | None:
        """从 XML 元素中获取文本。"""
        # Try plain tag first
        el = element.find(tag)
        if el is not None and el.text:
            return el.text.strip()

        # Try Atom namespace
        el = element.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
        if el is not None and el.text:
            return el.text.strip()

        return None

    @staticmethod
    def _parse_rss_date(text: str) -> datetime | None:
        """解析 RSS 日期格式。"""
        if not text:
            return None

        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(text.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None
