# src/crawlers/huggingface_crawler.py
from datetime import datetime, timezone
import re

import requests
from bs4 import BeautifulSoup
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class HuggingFaceCrawler(BaseCrawler):
    """爬取 HuggingFace Papers 页面的每日 AI 论文。"""

    def fetch(self) -> list[NewsItem]:
        url = self.config.get("url", "https://huggingface.co/papers")
        max_results = self.config.get("max_results", 20)

        try:
            resp = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"HuggingFace: failed to fetch papers: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = []

        # HuggingFace papers 页面结构
        paper_cards = soup.select("article.paper-card, div.paper-card, [data-paper-id]") or \
                      soup.select("a[href^='/papers/']")

        for card in paper_cards[:max_results]:
            try:
                item = self._parse_paper(card, soup)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"HuggingFace: failed to parse paper: {e}")
                continue

        # 如果上面选择器没找到，尝试解析页面中的论文列表
        if not items:
            items = self._parse_papers_fallback(resp.text, max_results)

        return self.filter_recent(items)

    def _parse_paper(self, card, soup) -> NewsItem | None:
        """解析单个论文卡片。"""
        # 获取标题和链接
        title_elem = card.select_one("h3, h2, .paper-title, [class*='title']")
        link_elem = card.select_one("a[href^='/papers/']") or card

        if not title_elem and link_elem:
            title_elem = link_elem

        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        href = link_elem.get("href", "") if link_elem else ""

        if not title or not href:
            return None

        if href.startswith("/"):
            url = f"https://huggingface.co{href}"
        else:
            url = href

        # 获取摘要
        abstract_elem = card.select_one(".abstract, [class*='abstract'], p")
        content = abstract_elem.get_text(strip=True)[:2000] if abstract_elem else title

        # 获取作者
        authors_elem = card.select_one(".authors, [class*='author']")
        author = authors_elem.get_text(strip=True) if authors_elem else "HuggingFace"

        # 尝试提取 arxiv ID 获取图片
        arxiv_id = self._extract_arxiv_id(url, card)
        image_url = ""
        if arxiv_id:
            image_url = self._get_arxiv_figure(arxiv_id)

        return NewsItem(
            source="huggingface",
            title=title,
            url=url,
            content=content,
            author=author,
            published_at=datetime.now(timezone.utc),
            tags=["paper", "huggingface"],
            raw_data={"arxiv_id": arxiv_id, "image_url": image_url},
        )

    def _parse_papers_fallback(self, html: str, max_results: int) -> list[NewsItem]:
        """备用解析方法：从页面中提取论文链接。"""
        items = []
        # 查找所有 /papers/ 链接
        paper_links = re.findall(r'href="(/papers/[^"]+)"', html)
        titles = re.findall(r'<[^>]*>([^<]{20,200})</[^>]*>', html)

        seen = set()
        for href in paper_links[:max_results]:
            if href in seen:
                continue
            seen.add(href)

            url = f"https://huggingface.co{href}"
            # 尝试从 URL 提取 arxiv ID
            arxiv_id = href.split("/")[-1] if "/" in href else ""
            image_url = self._get_arxiv_figure(arxiv_id) if arxiv_id else ""

            items.append(NewsItem(
                source="huggingface",
                title=f"Paper: {arxiv_id}",
                url=url,
                content="",
                author="HuggingFace",
                published_at=datetime.now(timezone.utc),
                tags=["paper", "huggingface"],
                raw_data={"arxiv_id": arxiv_id, "image_url": image_url},
            ))

        return items

    def _extract_arxiv_id(self, url: str, card) -> str:
        """从 URL 或卡片中提取 arxiv ID。"""
        # URL 中可能包含 arxiv ID
        match = re.search(r"(\d{4}\.\d{4,5}(v\d+)?)", url)
        if match:
            return match.group(1)

        # 卡片中可能有 arxiv 链接
        if card:
            arxiv_link = card.select_one("a[href*='arxiv.org']")
            if arxiv_link:
                href = arxiv_link.get("href", "")
                match = re.search(r"(\d{4}\.\d{4,5}(v\d+)?)", href)
                if match:
                    return match.group(1)

        return ""

    def _get_arxiv_figure(self, arxiv_id: str) -> str:
        """从 arxiv HTML 页获取论文图表。"""
        try:
            html_url = f"https://arxiv.org/html/{arxiv_id}"
            resp = requests.get(html_url, timeout=10,
                               headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"})
            if resp.status_code != 200:
                return ""

            imgs = re.findall(r'<img[^>]+src="([^"]+)"', resp.text)
            for img in imgs:
                if any(skip in img.lower() for skip in ("logo", "icon", "brand", "badge", "1x1")):
                    continue
                if img.startswith("//"):
                    img = "https:" + img
                elif img.startswith("/"):
                    img = f"https://arxiv.org{img}"
                elif not img.startswith("http"):
                    img = f"https://arxiv.org/html/{img}"
                return img
        except Exception:
            pass
        return ""
