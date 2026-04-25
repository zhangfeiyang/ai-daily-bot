# src/crawlers/arxiv_crawler.py
import re

import arxiv
import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class ArxivCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        categories = self.config.get("categories", ["cs.AI"])
        max_results = self.config.get("max_results", 20)
        sort_by = self.config.get("sort_by", "submittedDate")

        query = " OR ".join(f"cat:{cat}" for cat in categories)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=getattr(arxiv.SortCriterion, sort_by, arxiv.SortCriterion.SubmittedDate),
        )
        client = arxiv.Client()
        results = list(client.results(search))
        return self.filter_recent([self._parse_result(r) for r in results])

    def _parse_result(self, result) -> NewsItem:
        entry_id = result.entry_id
        # Extract arxiv ID from URL (e.g. https://arxiv.org/abs/2504.12345v1 -> 2504.12345v1)
        arxiv_id = entry_id.split("/abs/")[-1]

        # Try to get preview image from arxiv HTML page
        image_url = self._extract_arxiv_figure(arxiv_id)

        return NewsItem(
            source="arxiv",
            title=result.title.strip().replace("\n", " "),
            url=entry_id,
            content=result.summary.strip().replace("\n", " "),
            author=", ".join(a.name for a in result.authors),
            published_at=result.published,
            tags=result.categories,
            raw_data={
                "pdf_url": result.pdf_url,
                "categories": result.categories,
                "image_url": image_url,
            },
        )

    def _extract_arxiv_figure(self, arxiv_id: str) -> str:
        """Try to extract the first figure from arxiv HTML page."""
        try:
            html_url = f"https://arxiv.org/html/{arxiv_id}"
            resp = requests.get(html_url, timeout=10,
                               headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"})
            if resp.status_code != 200:
                return ""
            # Find the first <img> with a meaningful src (skip logos/icons)
            imgs = re.findall(r'<img[^>]+src="([^"]+)"', resp.text)
            for img in imgs:
                # Skip tiny icons, logos, and brand images
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
