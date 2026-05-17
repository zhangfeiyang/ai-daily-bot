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

    SEARCH_STOPWORDS = {
        "a", "an", "and", "are", "as", "at", "by", "for", "from", "he", "in",
        "is", "it", "joins", "of", "on", "or", "she", "the", "to", "will",
        "with", "ai",
    }

    def _fetch(self) -> list[NewsItem]:
        subreddits = self.config.get("subreddits", ["MachineLearning"])
        limit = self.config.get("limit", 15)
        min_score = self.config.get("min_score", 20)
        time_filter = self.config.get("time_filter", "day")
        sort = self.config.get("sort", "top")
        require_query_match = bool(self.config.get("search_queries", []))
        search_queries = self._build_search_queries(subreddits)

        items = self._fetch_search_results(
            search_queries,
            limit,
            min_score=min_score,
            time_filter=time_filter,
            sort=sort,
            require_query_match=require_query_match,
        )
        return self.filter_recent(items)

    def get_cache_key(self) -> str:
        queries = self.config.get("search_queries") or self.config.get("subreddits") or []
        if isinstance(queries, str):
            queries = [queries]
        parts = [
            "reddit-search-v2",
            f"time={self.config.get('time_filter', 'day')}",
            f"sort={self.config.get('sort', 'top')}",
            f"limit={self.config.get('limit', 15)}",
            f"min_score={self.config.get('min_score', 20)}",
            *[str(query).strip() for query in queries if str(query).strip()],
        ]
        return "|".join(parts)

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
        time_filter: str | None = "day",
        sort: str | None = "top",
        require_query_match: bool = False,
    ) -> list[NewsItem]:
        """Use OpenCLI Reddit search when explicit search queries are configured."""
        items: list[NewsItem] = []
        seen_urls: set[str] = set()

        for query in search_queries:
            try:
                results = opencli_reddit_search(
                    str(query),
                    limit=limit,
                    time_filter=time_filter,
                    sort=sort,
                )
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
                if require_query_match and not self._matches_search_query(query, title, content):
                    continue

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
                            "search_time_filter": time_filter,
                            "search_sort": sort,
                            "published_at_source": "opencli_reddit_search_window",
                        },
                    )
                )

                if len(items) >= limit:
                    return items

        return items

    @classmethod
    def _matches_search_query(cls, query: str, title: str, content: str = "") -> bool:
        """Reject OpenCLI Reddit fallback results that do not match the requested topic."""
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]*", query.lower())
            if len(token) >= 3 and token not in cls.SEARCH_STOPWORDS
        ]
        if not tokens:
            return True
        haystack = f"{title} {content}".lower()
        return any(token in haystack for token in tokens)

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
