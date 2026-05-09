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

        # HuggingFace papers 页面结构：每篇论文有 article 元素
        # 在 article 内部，h3 包含标题，h3 > a 包含论文链接
        paper_articles = soup.select("article")

        seen_urls = set()
        for article in paper_articles:
            try:
                # 查找 h3 中的论文链接（这是标题链接）
                title_link = article.select_one("h3 > a[href^='/papers/']")
                if not title_link:
                    continue

                href = title_link.get("href", "")
                # 过滤非论文链接和重复链接
                if not re.match(r'^/papers/\d{4}\.\d{4,5}', href):
                    continue
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                # 获取标题
                title = title_link.get_text(strip=True)
                if not title:
                    continue

                item = self._create_news_item(title, href, article)
                if item:
                    items.append(item)

                if len(items) >= max_results:
                    break
            except Exception as e:
                logger.debug(f"HuggingFace: failed to parse paper: {e}")
                continue

        # 如果上面选择器没找到，尝试解析页面中的论文列表
        if not items:
            items = self._parse_papers_fallback(resp.text, max_results)

        return self.filter_recent(items)

    def _create_news_item(self, title: str, href: str, article) -> NewsItem | None:
        """创建 NewsItem 对象。"""
        url = f"https://huggingface.co{href}"

        # 获取摘要
        abstract_elem = article.select_one(".abstract, [class*='abstract'], p")
        content = abstract_elem.get_text(strip=True)[:2000] if abstract_elem else title

        # 获取作者
        authors_elem = article.select_one(".authors, [class*='author']")
        author = authors_elem.get_text(strip=True) if authors_elem else "HuggingFace"

        # 尝试提取 arxiv ID 获取图片
        arxiv_id = self._extract_arxiv_id(url, article)
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

    def _parse_paper(self, card, soup) -> NewsItem | None:
        """解析单个论文卡片（备用方法）。"""
        # 获取链接
        link_elem = card.select_one("a[href^='/papers/']") or card
        href = link_elem.get("href", "") if link_elem else ""

        # 过滤掉非论文链接（如导航链接）
        if not re.match(r'^/papers/\d{4}\.\d{4,5}', href):
            return None

        # 获取标题：优先查找标题元素，否则从链接文本获取
        title_elem = card.select_one("h3, h2, .paper-title, [class*='title']")
        if title_elem:
            title = title_elem.get_text(strip=True)
        else:
            # 从页面中查找对应的标题
            title = self._find_paper_title(soup, href)

        if not title:
            # 从 URL 提取 arxiv ID 作为标题
            arxiv_id = href.split("/")[-1] if "/" in href else ""
            title = f"Paper: {arxiv_id}"

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

    def _find_paper_title(self, soup, href: str) -> str:
        """从页面中查找论文标题。"""
        # 查找指向该论文的链接，获取其完整文本
        link = soup.select_one(f"a[href='{href}']")
        if link:
            # 获取链接的完整文本内容
            text = link.get_text(strip=True)
            # 如果文本看起来像标题（长度合理且不是作者信息）
            if text and len(text) > 20 and not text.startswith("·") and not text.isdigit():
                return text
        return ""

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
