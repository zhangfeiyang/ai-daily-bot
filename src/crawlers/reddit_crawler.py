# src/crawlers/reddit_crawler.py
from datetime import datetime, timezone
import re

from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem
from src.utils.opencli_search import reddit_search as opencli_reddit_search


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

    def _fetch(self) -> list[NewsItem]:
        subreddits = self.config.get("subreddits", ["MachineLearning"])
        limit = self.config.get("limit", 15)
        min_score = self.config.get("min_score", 20)
        search_queries = self._build_search_queries(subreddits)

        items = self._fetch_search_results(search_queries, limit, min_score=min_score)
        return self.filter_recent(items)

    def _build_search_queries(self, subreddits: list[str]) -> list[str]:
        """Build OpenCLI search queries from explicit search queries or subreddits."""
        search_queries = self.config.get("search_queries", [])
        if search_queries:
            return [str(query).strip() for query in search_queries if str(query).strip()]
        return [str(sub).strip() for sub in subreddits if str(sub).strip()]

    def _fetch_search_results(
        self,
        search_queries: list[str],
        limit: int,
        min_score: int = 20,
    ) -> list[NewsItem]:
        """Use OpenCLI Reddit search when explicit search queries are configured."""
        items: list[NewsItem] = []
        seen_urls: set[str] = set()

        for query in search_queries:
            try:
                results = opencli_reddit_search(str(query), limit=limit)
            except Exception as e:
                logger.debug(f"Reddit: OpenCLI search failed for query {query!r}: {e}")
                continue

            for result in results:
                url = result.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = result.get("title", "")
                if not title:
                    continue

                score = result.get("score")
                if score is not None:
                    try:
                        if int(score) < min_score:
                            continue
                    except (TypeError, ValueError):
                        pass
                elif self._is_low_quality_title(title):
                    continue

                subreddit = result.get("subreddit", "")
                author = result.get("author", "")
                comments = result.get("comments")
                content = result.get("snippet", "") or title

                items.append(
                    NewsItem(
                        source="reddit",
                        title=title,
                        url=url,
                        content=content[:2000],
                        author=author,
                        published_at=datetime.now(timezone.utc),
                        tags=[t for t in [subreddit, "reddit"] if t],
                        raw_data={
                            "subreddit": subreddit,
                            "reddit_score": score,
                            "reddit_comments": comments,
                            "search_query": query,
                        },
                    )
                )

                if len(items) >= limit:
                    return items

        return items

    def _is_low_quality_title(self, title: str) -> bool:
        title_lower = title.lower()
        return any(kw in title_lower for kw in self.LOW_QUALITY_KEYWORDS)

    def _assess_post_quality(self, title: str, entry) -> str:
        """Legacy quality heuristic kept for compatibility with older tests."""
        title_lower = title.lower()
        if any(kw in title_lower for kw in self.LOW_QUALITY_KEYWORDS):
            return "low"
        if any(indicator in title_lower for indicator in self.HIGH_QUALITY_INDICATORS):
            return "high"
        return "medium"
