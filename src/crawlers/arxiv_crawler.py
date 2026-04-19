# src/crawlers/arxiv_crawler.py
import arxiv
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
        return [self._parse_result(r) for r in results]

    def _parse_result(self, result) -> NewsItem:
        return NewsItem(
            source="arxiv",
            title=result.title.strip().replace("\n", " "),
            url=result.entry_id,
            content=result.summary.strip().replace("\n", " "),
            author=", ".join(a.name for a in result.authors),
            published_at=result.published,
            tags=result.categories,
            raw_data={
                "pdf_url": result.pdf_url,
                "categories": result.categories,
            },
        )
