# src/crawlers/changelog_crawler.py
"""监控 AI 工具/Agent 的官方 Changelog / Release Notes 页面。

支持的来源：
- Claude Code: https://code.claude.com/docs/en/changelog
- OpenAI Codex: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md (示例，实际需替换)
- Cursor: https://www.cursor.com/changelog
- 其他工具可通过配置扩展

抓取策略：
1. 抓取页面 HTML
2. 提取最近的变更条目（基于日期或版本号）
3. 只返回 24h/72h 内的更新（由 max_age_hours 控制）
"""

from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import re

import requests
from bs4 import BeautifulSoup
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


def _github_api_releases(repo: str, max_age_hours: int, per_page: int = 10) -> list[NewsItem]:
    """Fetch recent releases from GitHub API."""
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    api_url = f"https://api.github.com/repos/{repo}/releases"
    try:
        resp = requests.get(
            api_url,
            params={"per_page": per_page},
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)",
                "Accept": "application/vnd.github+json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        releases = resp.json()
        for rel in releases:
            published = rel.get("published_at", "")
            if not published:
                continue
            try:
                parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed < cutoff:
                continue
            tag = rel.get("tag_name", "")
            name = rel.get("name", tag)
            body = rel.get("body", "") or ""
            html_url = rel.get("html_url", "")
            # Clean up markdown body
            content = body.strip()
            if not content:
                content = f"Release {tag}"
            tool_name = repo.split("/")[-1].replace("-", " ").title()
            items.append(NewsItem(
                source="changelog",
                title=f"{tool_name} {tag} 发布",
                url=html_url,
                content=content[:3000],
                author=tool_name,
                published_at=parsed,
                tags=["changelog", tool_name.lower().replace(" ", "-")],
                raw_data={
                    "tool_name": tool_name,
                    "version": tag,
                    "changelog_url": html_url,
                    "links": [html_url],
                },
            ))
    except Exception as e:
        logger.warning(f"GitHub API releases failed for {repo}: {e}")
    return items


def _fetch_with_playwright(url: str, wait_selector: str | None = None, timeout: int = 30) -> str | None:
    """Use Playwright to fetch JavaScript-rendered page content."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = None
            for browser_type in [p.firefox, p.chromium]:
                try:
                    browser = browser_type.launch(
                        headless=True,
                        args=["--no-sandbox"] if browser_type == p.chromium else [],
                    )
                    break
                except Exception:
                    continue

            if not browser:
                logger.warning("No browser available for Playwright")
                return None

            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            # Wait for content
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=10000)
                except Exception:
                    pass
            else:
                page.wait_for_timeout(3000)

            html = page.content()
            context.close()
            browser.close()
            return html

    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
        return None


# 默认监控的 changelog 源
_DEFAULT_SOURCES = [
    {
        "name": "claude-code",
        "tool_name": "Claude Code",
        "url": "https://code.claude.com/docs/en/changelog",
        "type": "claude_docs",
        "enabled": True,
    },
    {
        "name": "cursor",
        "tool_name": "Cursor",
        "url": "https://www.cursor.com/changelog",
        "type": "cursor_blog",
        "enabled": True,
    },
    {
        "name": "codex-github",
        "tool_name": "OpenAI Codex",
        "url": "https://github.com/openai/codex/blob/main/CHANGELOG.md",
        "type": "github_markdown",
        "enabled": True,
    },
    {
        "name": "openclaw",
        "tool_name": "OpenClaw",
        "url": "https://github.com/OpenClawAI/OpenClaw/blob/main/CHANGELOG.md",
        "type": "github_markdown",
        "enabled": True,
    },
    {
        "name": "claude-code-github",
        "tool_name": "Claude Code",
        "url": "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md",
        "type": "github_markdown",
        "enabled": True,
    },
]


class ChangelogCrawler(BaseCrawler):
    """监控 AI 工具的官方 Changelog 页面。"""

    def _fetch(self) -> list[NewsItem]:
        sources = self.config.get("sources", _DEFAULT_SOURCES)
        max_results = self.config.get("max_results", 30)
        max_age_hours = self.config.get("max_age_hours", 72)
        items: list[NewsItem] = []

        for src in sources:
            if not src.get("enabled", True):
                continue
            try:
                src_items = self._fetch_source(src, max_age_hours)
                items.extend(src_items)
                logger.info(f"Changelog/{src['name']}: {len(src_items)} items")
            except Exception as e:
                logger.warning(f"Changelog/{src['name']} failed: {e}")

        items = self.filter_recent(items)
        return items[:max_results]

    def _fetch_source(self, src: dict, max_age_hours: int) -> list[NewsItem]:
        """抓取单个 changelog 源。"""
        url = src["url"]
        tool_name = src.get("tool_name", src["name"])
        src_type = src.get("type", "auto")
        needs_js = src.get("javascript", False)

        # 优先使用 GitHub API 获取 releases（更可靠）
        if src_type == "github_releases":
            repo = src.get("repo", "")
            if repo:
                return _github_api_releases(repo, max_age_hours, src.get("per_page", 10))
            return []

        html = None
        if needs_js:
            # Use Playwright for JavaScript-rendered pages
            html = _fetch_with_playwright(url, wait_selector=src.get("wait_selector"), timeout=self.config.get("timeout", 30))

        if html is None:
            resp = requests.get(
                url,
                timeout=self.config.get("timeout", 30),
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        # 根据类型选择解析器
        if src_type == "auto":
            src_type = self._detect_page_type(soup, url)

        if src_type == "claude_docs":
            return self._parse_claude_docs(soup, url, tool_name, max_age_hours)
        elif src_type == "cursor_blog":
            return self._parse_cursor_blog(soup, url, tool_name, max_age_hours)
        elif src_type == "github_markdown":
            return self._parse_github_markdown(soup, url, tool_name, max_age_hours)
        else:
            return self._parse_generic(soup, url, tool_name, max_age_hours)

    @staticmethod
    def _detect_page_type(soup: BeautifulSoup, url: str) -> str:
        """自动检测页面类型。"""
        if "code.claude.com" in url:
            return "claude_docs"
        if "cursor.com" in url and "changelog" in url:
            return "cursor_blog"
        if "github.com" in url and "CHANGELOG.md" in url:
            return "github_markdown"
        return "generic"

    def _parse_claude_docs(self, soup: BeautifulSoup, url: str, tool_name: str, max_age_hours: int) -> list[NewsItem]:
        """解析 Claude Code 官方文档 changelog 页面。

        页面结构（Mintlify/Next.js SPA）：
        每个更新是一个 <div class="update ...">，内部包含版本号、日期和变更列表。
        示例：
        <div class="update ...">
            <div>2.1.140</div>
            <div>May 12, 2026</div>
            <ul><li>Fixed ...</li></ul>
        </div>
        """
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # 策略1：查找 class 包含 "update" 的 div（实际页面结构）
        update_divs = soup.find_all("div", class_=re.compile(r"\bupdate\b"))

        # 策略2：如果找不到，回退到基于日期的通用解析
        if not update_divs:
            return self._parse_claude_docs_fallback(soup, url, tool_name, max_age_hours)

        for div in update_divs:
            text = div.get_text(separator="\n", strip=True)
            if not text or len(text) < 20:
                continue

            # 提取日期
            parsed_date = None
            date_text = ""
            # 在 div 内找日期文本
            for elem in div.find_all(string=re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\s,]+\d{1,2}[\s,]+\d{4}")):
                date_text = elem.strip()
                parsed_date = self._parse_date(date_text)
                if parsed_date:
                    break

            if not parsed_date or parsed_date < cutoff:
                continue

            # 提取版本号
            version = ""
            version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', text)
            if version_match:
                version = version_match.group(1)

            # 提取变更条目（ul/li 或直接按行分割）
            entries = []
            for li in div.find_all("li"):
                li_text = li.get_text(strip=True)
                if li_text and len(li_text) > 5:
                    entries.append(li_text)

            # 如果没有 li，尝试按行分割
            if not entries:
                for line in text.split("\n"):
                    line = line.strip()
                    # 跳过版本号和日期行
                    if re.match(r'^\d+\.\d+', line) or self._parse_date(line):
                        continue
                    if line and len(line) > 10:
                        entries.append(line)

            if not entries:
                continue

            content = "\n".join(f"- {e}" for e in entries)
            title = f"{tool_name} {version} 发布" if version else f"{tool_name} 更新 ({date_text})"

            items.append(NewsItem(
                source="changelog",
                title=title,
                url=url,
                content=content,
                author=tool_name,
                published_at=parsed_date,
                tags=["changelog", tool_name.lower().replace(" ", "-")],
                raw_data={
                    "tool_name": tool_name,
                    "version": version,
                    "changelog_url": url,
                    "entries": entries,
                    "links": [url],
                },
            ))

        return items

    def _parse_claude_docs_fallback(self, soup: BeautifulSoup, url: str, tool_name: str, max_age_hours: int) -> list[NewsItem]:
        """Claude Code changelog 回退解析器（基于 h2/h3 标题）。"""
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        for heading in soup.find_all(["h2", "h3"]):
            date_text = heading.get_text(strip=True)
            parsed_date = self._parse_date(date_text)
            if not parsed_date or parsed_date < cutoff:
                continue

            entries = []
            sibling = heading.find_next_sibling()
            while sibling and sibling.name not in ("h2", "h3"):
                if sibling.name in ("ul", "ol"):
                    for li in sibling.find_all("li"):
                        text = li.get_text(strip=True)
                        if text:
                            entries.append(text)
                elif sibling.name == "p":
                    text = sibling.get_text(strip=True)
                    if text:
                        entries.append(text)
                sibling = sibling.find_next_sibling()

            if not entries:
                continue

            content = "\n".join(f"- {e}" for e in entries)
            title = f"{tool_name} 更新 ({date_text}): {entries[0][:50]}"

            items.append(NewsItem(
                source="changelog",
                title=title,
                url=url,
                content=content,
                author=tool_name,
                published_at=parsed_date,
                tags=["changelog", tool_name.lower().replace(" ", "-")],
                raw_data={
                    "tool_name": tool_name,
                    "changelog_url": url,
                    "entries": entries,
                    "links": [url],
                },
            ))

        return items

    def _parse_cursor_blog(self, soup: BeautifulSoup, url: str, tool_name: str, max_age_hours: int) -> list[NewsItem]:
        """解析 Cursor Changelog 页面。

        通常是博客列表形式，每个版本一篇文章。
        """
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # 尝试多种常见结构
        # 1. 文章卡片列表 - 合并并去重
        articles = []
        seen_articles = set()
        for elem in soup.find_all("article") + soup.find_all("div", class_=re.compile(r"post|entry|article|changelog", re.I)):
            # 用文本内容指纹去重
            fingerprint = elem.get_text(strip=True)[:100]
            if fingerprint not in seen_articles:
                seen_articles.add(fingerprint)
                articles.append(elem)

        for article in articles:
            # 提取日期 - 先尝试 <time> 标签（无论 class 是什么）
            date_elem = article.find("time")
            if not date_elem:
                date_elem = article.find(["time", "span", "div"], class_=re.compile(r"date|time", re.I))
            date_text = date_elem.get_text(strip=True) if date_elem else ""
            # 尝试从 datetime 属性提取
            if not date_text and date_elem and date_elem.get("datetime"):
                date_text = date_elem.get("datetime")
            if not date_text:
                # 尝试从标题中提取日期
                title_elem = article.find(["h1", "h2", "h3"])
                if title_elem:
                    date_text = title_elem.get_text(strip=True)

            parsed_date = self._parse_date(date_text)
            if not parsed_date or parsed_date < cutoff:
                continue

            # 提取标题和内容
            title_elem = article.find(["h1", "h2", "h3", "h4"])
            title = title_elem.get_text(strip=True) if title_elem else f"{tool_name} 更新"

            # 提取正文 - 优先找内容区域，否则用整个 article
            content_elem = article.find("div", class_=re.compile(r"content|body|excerpt", re.I)) or article
            content = content_elem.get_text(separator="\n", strip=True)

            # 清理元信息：日期行、"Changelog" 标签、中间点分隔符
            lines = content.split("\n")
            cleaned_lines = []
            skip_patterns = [
                re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\s,]+\d{1,2}[\s,]+\d{4}"),
                re.compile(r"^\d{4}-\d{2}-\d{2}"),
                re.compile(r"^changelog$", re.I),
                re.compile(r"^·$"),
                re.compile(r"^\s*$"),
            ]
            for line in lines:
                stripped = line.strip()
                if any(p.match(stripped) for p in skip_patterns):
                    continue
                cleaned_lines.append(stripped)

            content = "\n".join(cleaned_lines)
            # 清理多余空白
            content = re.sub(r"\n{3,}", "\n\n", content)

            if len(content) < 20:
                continue

            # 提取链接
            link_elem = article.find("a", href=True)
            article_url = urljoin(url, link_elem["href"]) if link_elem else url

            items.append(NewsItem(
                source="changelog",
                title=f"{tool_name}: {title}" if not title.startswith(tool_name) else title,
                url=article_url,
                content=content[:2000],
                author=tool_name,
                published_at=parsed_date,
                tags=["changelog", tool_name.lower().replace(" ", "-")],
                raw_data={
                    "tool_name": tool_name,
                    "changelog_url": url,
                    "links": [article_url, url],
                },
            ))

        return items

    def _parse_github_markdown(self, soup: BeautifulSoup, url: str, tool_name: str, max_age_hours: int) -> list[NewsItem]:
        """解析 GitHub 上的 CHANGELOG.md 页面。

        GitHub 渲染后的 Markdown 结构：
        <h2>v1.2.3 (2026-05-12)</h2>
        <ul><li>变更内容</li></ul>
        """
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # GitHub 渲染后的 markdown 内容在 article 或 div.markdown-body 中
        container = soup.find("article", class_="markdown-body") or soup.find("div", class_="markdown-body")
        if not container:
            container = soup

        for heading in container.find_all(["h2", "h3"]):
            heading_text = heading.get_text(strip=True)
            # 提取版本号和日期
            version_match = re.search(r'(v?\d+\.\d+(?:\.\d+)?)', heading_text)
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2})', heading_text)

            parsed_date = None
            if date_match:
                parsed_date = self._parse_date(date_match.group(1))
            if not parsed_date:
                parsed_date = self._parse_date(heading_text)

            if not parsed_date or parsed_date < cutoff:
                continue

            # 收集该版本下的条目
            entries = []
            sibling = heading.find_next_sibling()
            while sibling and sibling.name not in ("h2", "h3"):
                if sibling.name in ("ul", "ol"):
                    for li in sibling.find_all("li"):
                        text = li.get_text(strip=True)
                        if text:
                            entries.append(text)
                elif sibling.name == "p":
                    text = sibling.get_text(strip=True)
                    if text and not text.startswith("-"):
                        entries.append(text)
                sibling = sibling.find_next_sibling()

            if not entries:
                continue

            version = version_match.group(1) if version_match else "新版本"
            content = "\n".join(f"- {e}" for e in entries)
            title = f"{tool_name} {version} 发布"

            items.append(NewsItem(
                source="changelog",
                title=title,
                url=url,
                content=content,
                author=tool_name,
                published_at=parsed_date,
                tags=["changelog", tool_name.lower().replace(" ", "-")],
                raw_data={
                    "tool_name": tool_name,
                    "version": version,
                    "changelog_url": url,
                    "entries": entries,
                    "links": [url],
                },
            ))

        return items

    def _parse_generic(self, soup: BeautifulSoup, url: str, tool_name: str, max_age_hours: int) -> list[NewsItem]:
        """通用解析器：尝试从页面提取带日期的条目列表。"""
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # 策略：找所有可能包含日期和文本的元素组合
        # 先尝试找日期元素，然后收集后续内容
        date_patterns = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\s,]+\d{1,2}[\s,]+\d{4}", re.I)

        for elem in soup.find_all(text=date_patterns):
            parent = elem.parent
            date_text = elem.strip()
            parsed_date = self._parse_date(date_text)
            if not parsed_date or parsed_date < cutoff:
                continue

            # 尝试找同级的标题/内容
            container = parent.find_parent(["div", "section", "article"]) or parent
            title_elem = container.find(["h1", "h2", "h3", "h4"])
            title = title_elem.get_text(strip=True) if title_elem else f"{tool_name} 更新"

            content = container.get_text(separator="\n", strip=True)
            content = re.sub(r"\n{3,}", "\n\n", content)

            if len(content) < 20:
                continue

            items.append(NewsItem(
                source="changelog",
                title=f"{tool_name}: {title}" if not title.startswith(tool_name) else title,
                url=url,
                content=content[:2000],
                author=tool_name,
                published_at=parsed_date,
                tags=["changelog", tool_name.lower().replace(" ", "-")],
                raw_data={
                    "tool_name": tool_name,
                    "changelog_url": url,
                    "links": [url],
                },
            ))

        return items

    @staticmethod
    def _parse_date(text: str) -> datetime | None:
        """从文本中提取日期。"""
        if not text:
            return None

        text = text.strip()

        # ISO 格式: 2026-05-12
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            except ValueError:
                pass

        # 斜杠格式: 2026/05/12
        m = re.search(r'(\d{4})/(\d{2})/(\d{2})', text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            except ValueError:
                pass

        # 英文月份: May 12, 2026 或 May 12 2026
        month_map = {
            "january": 1, "jan": 1,
            "february": 2, "feb": 2,
            "march": 3, "mar": 3,
            "april": 4, "apr": 4,
            "may": 5,
            "june": 6, "jun": 6,
            "july": 7, "jul": 7,
            "august": 8, "aug": 8,
            "september": 9, "sep": 9, "sept": 9,
            "october": 10, "oct": 10,
            "november": 11, "nov": 11,
            "december": 12, "dec": 12,
        }
        m = re.search(r'([A-Za-z]{3,9})[\s,]+(\d{1,2})[\s,]+(\d{4})', text, re.I)
        if m:
            month_str = m.group(1).lower()
            if month_str in month_map:
                try:
                    return datetime(int(m.group(3)), month_map[month_str], int(m.group(2)), tzinfo=timezone.utc)
                except ValueError:
                    pass

        # 相对日期: "2 days ago", "yesterday"
        lower = text.lower()
        now = datetime.now(timezone.utc)
        if "today" in lower:
            return now
        if "yesterday" in lower:
            return now - timedelta(days=1)
        m = re.search(r'(\d+)\s+day[s]?\s+ago', lower)
        if m:
            return now - timedelta(days=int(m.group(1)))

        return None
