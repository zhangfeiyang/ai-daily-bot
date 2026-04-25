# src/crawlers/github_crawler.py
from datetime import datetime, timezone, timedelta
import re

import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class GitHubCrawler(BaseCrawler):
    """通过 GitHub Search API 爬取 AI 相关热门仓库。"""

    def fetch(self) -> list[NewsItem]:
        topics = self.config.get("topics", ["machine-learning", "deep-learning", "llm"])
        languages = self.config.get("languages", ["python"])
        min_stars = self.config.get("min_stars", 5)
        max_results = self.config.get("max_results", 20)
        max_age_hours = self.config.get("max_age_hours", 72)

        items = []
        # 搜索最近创建的 AI 相关仓库
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        date_str = cutoff.strftime("%Y-%m-%d")

        for topic in topics:
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
                    item = self._parse_repo(repo, min_stars)
                    if item:
                        items.append(item)

            except Exception as e:
                logger.debug(f"GitHub: search failed for topic {topic}: {e}")

        return items[:max_results]

    def _parse_repo(self, repo: dict, min_stars: int) -> NewsItem | None:
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

        tags = ["github"] + [t for t in topics if t][:3]
        if language:
            tags.append(language.lower())

        title = f"{repo_name}: {description[:80]}" if description else repo_name

        # GitHub social preview image
        image_url = f"https://opengraph.githubassets.com/1/{full_name}"

        return NewsItem(
            source="github",
            title=title,
            url=url,
            content=description[:2000],
            author=owner,
            published_at=datetime.now(timezone.utc),
            tags=tags,
            raw_data={
                "full_name": full_name,
                "language": language,
                "stars": str(stars),
                "image_url": image_url,
            },
        )
