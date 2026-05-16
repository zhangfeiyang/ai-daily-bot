# src/crawlers/github_crawler.py
from datetime import datetime, timezone, timedelta
import re

import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem
from src.utils.opencli_search import google_search as opencli_google_search


class GitHubCrawler(BaseCrawler):
    """通过 GitHub Search API 爬取 AI 相关热门仓库。"""

    def _fetch(self) -> list[NewsItem]:
        topics = self.config.get("topics", ["machine-learning", "deep-learning", "llm"])
        topic_limit = self.config.get("topic_limit")
        if topic_limit:
            topics = topics[: int(topic_limit)]
        languages = self.config.get("languages", ["python"])
        min_stars = self.config.get("min_stars", 5)
        max_results = self.config.get("max_results", 20)
        max_age_hours = self.config.get("max_age_hours", 72)

        items = []
        # 搜索最近创建的 AI 相关仓库
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        date_str = cutoff.strftime("%Y-%m-%d")

        for topic in topics:
            opencli_items = self._fetch_opencli_repos(
                topic=topic,
                language=languages[0] if languages else "",
                min_stars=min_stars,
                max_results=max_results,
                cutoff=cutoff,
            )
            items.extend(opencli_items)
            if len(items) >= max_results:
                return items[:max_results]

            try:
                query = f"{topic}+created:>{date_str}"
                if languages:
                    query += f"+language:{languages[0]}"

                from urllib.parse import quote
                # Build URL manually to avoid double-encoding of > in query
                encoded_q = quote(query, safe="+:")
                api_url = (
                    f"https://api.github.com/search/repositories"
                    f"?q={encoded_q}&sort=stars&order=desc&per_page={min(max_results, 30)}"
                )
                resp = requests.get(
                    api_url,
                    timeout=30,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("items"):
                    continue

                for repo in data.get("items", []):
                    item = self._parse_repo(repo, min_stars, cutoff=cutoff)
                    if item:
                        items.append(item)
                    if len(items) >= max_results:
                        return items[:max_results]

            except Exception as e:
                logger.debug(f"GitHub: search failed for topic {topic}: {e}")

        return items[:max_results]

    def _fetch_opencli_repos(
        self,
        topic: str,
        language: str,
        min_stars: int,
        max_results: int,
        cutoff: datetime | None = None,
    ) -> list[NewsItem]:
        """Use OpenCLI Google search to discover GitHub repos, then enrich via GitHub API."""
        query_parts = [f"site:github.com {topic}"]
        if language:
            query_parts.append(language)
        query = " ".join(query_parts)

        try:
            results = opencli_google_search(query, limit=max_results * 2)
        except Exception as e:
            logger.debug(f"GitHub: OpenCLI search failed for topic {topic}: {e}")
            return []

        items: list[NewsItem] = []
        seen: set[str] = set()
        for result in results:
            full_name = self._extract_repo_full_name(result.get("url", ""))
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)

            repo = self._fetch_repo_metadata(full_name)
            if not repo:
                continue

            item = self._parse_repo(repo, min_stars, cutoff=cutoff)
            if item:
                items.append(item)
            if len(items) >= max_results:
                break

        return items

    @staticmethod
    def _extract_repo_full_name(url: str) -> str:
        """Extract owner/repo from a GitHub URL."""
        if not url:
            return ""

        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host not in {"github.com", "www.github.com"}:
            return ""

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return ""

        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        if not owner or not repo:
            return ""

        return f"{owner}/{repo}"

    @staticmethod
    def _fetch_repo_metadata(full_name: str) -> dict | None:
        """Fetch GitHub repo metadata for a full repository name."""
        try:
            api_url = f"https://api.github.com/repos/{full_name}"
            resp = requests.get(
                api_url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"GitHub: failed to fetch repo metadata for {full_name}: {e}")
            return None

    def _parse_repo(self, repo: dict, min_stars: int, cutoff: datetime | None = None) -> NewsItem | None:
        """解析 GitHub API 返回的仓库数据。"""
        full_name = repo.get("full_name", "")
        stars = repo.get("stargazers_count", 0)

        if not full_name or stars < min_stars:
            return None

        parts = full_name.split("/")
        owner = parts[0]
        repo_name = parts[1] if len(parts) >= 2 else full_name
        description = repo.get("description", "") or ""
        url = repo.get("html_url", f"https://github.com/{full_name}")
        language = repo.get("language", "") or ""
        topics = repo.get("topics", [])

        # Filter out repos without meaningful description
        if not description or len(description.strip()) < 10:
            return None

        tags = ["github"] + [t for t in topics if t][:3]
        if language:
            tags.append(language.lower())

        title = f"{repo_name}({stars}⭐): {description[:70]}" if description else repo_name

        # GitHub social preview image
        image_url = f"https://opengraph.githubassets.com/1/{full_name}"

        # Use actual creation date from GitHub API
        created_at = repo.get("created_at")
        if created_at:
            try:
                from datetime import datetime as dt
                published_at = dt.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                published_at = datetime.now(timezone.utc)
        else:
            published_at = datetime.now(timezone.utc)

        if cutoff and published_at < cutoff:
            return None

        return NewsItem(
            source="github",
            title=title,
            url=url,
            content=description[:2000],
            author=owner,
            published_at=published_at,
            tags=tags,
            raw_data={
                "full_name": full_name,
                "language": language,
                "stars": str(stars),
                "image_url": image_url,
            },
        )
