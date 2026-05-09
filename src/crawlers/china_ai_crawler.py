# src/crawlers/china_ai_crawler.py
"""爬取国内 AI 科技媒体文章。

通过 RSS/WordPress API/jina.ai 代理获取国内 AI 新闻。
支持：量子位、新智元、机器之心、智东西、雷锋网
"""

from datetime import datetime, timezone, timedelta
import re
import html as html_lib
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem

# 国内 AI 新闻源
SOURCES = {
    "quantumbit": {
        "name": "量子位",
        "type": "wordpress_api",
        "api_url": "https://www.qbitai.com/wp-json/wp/v2/posts",
        "base_url": "https://www.qbitai.com",
    },
    "aiera": {
        "name": "新智元",
        "type": "wordpress_api",
        "api_url": "https://aiera.com.cn/wp-json/wp/v2/posts",
        "base_url": "https://aiera.com.cn",
    },
    "jiqizhixin": {
        "name": "机器之心",
        "type": "jina_proxy",
        "list_url": "https://www.jiqizhixin.com/articles",
        "article_base": "https://www.jiqizhixin.com/articles",
        "base_url": "https://www.jiqizhixin.com",
    },
    "zhidx": {
        "name": "智东西",
        "type": "rss",
        "rss": "https://www.zhidx.com/rss",
        "base_url": "https://www.zhidx.com",
    },
    "leiphone": {
        "name": "雷锋网",
        "type": "rss",
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
    """爬取国内 AI 科技媒体的文章。"""

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
                if source_cfg.get("type") == "wordpress_api":
                    source_items = self._fetch_wordpress(source_key, source_cfg, max_age_hours)
                elif source_cfg.get("type") == "jina_proxy":
                    source_items = self._fetch_jina(source_key, source_cfg, max_age_hours)
                else:
                    source_items = self._fetch_rss(source_key, source_cfg, max_age_hours)

                if filter_companies:
                    source_items = self._filter_china_ai(source_items)
                items.extend(source_items)
                logger.debug(f"ChinaAI {source_cfg['name']}: {len(source_items)} items")
            except Exception as e:
                logger.warning(f"ChinaAI {source_cfg['name']} failed: {e}")

        return items[:max_results]

    def _fetch_wordpress(
        self,
        source_key: str,
        source_cfg: dict,
        max_age_hours: int,
    ) -> list[NewsItem]:
        """通过 WordPress REST API 获取文章。"""
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        per_page = self.config.get("per_page", 50)

        try:
            resp = requests.get(
                source_cfg["api_url"],
                params={
                    "per_page": per_page,
                    "_fields": "id,title,link,content,excerpt,date,author",
                },
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
            )
            if resp.status_code != 200:
                logger.warning(f"WordPress API failed for {source_cfg['name']}: {resp.status_code}")
                return items
        except Exception as e:
            logger.debug(f"WordPress fetch failed for {source_cfg['name']}: {e}")
            return items

        try:
            posts = resp.json()
        except Exception:
            return items

        for post in posts:
            title = post.get("title", {}).get("rendered", "")
            link = post.get("link", "")
            content_html = post.get("content", {}).get("rendered", "")
            excerpt_html = post.get("excerpt", {}).get("rendered", "")
            date_str = post.get("date", "")

            if not title or not link:
                continue

            # Parse date
            pub_date = self._parse_wp_date(date_str)
            if pub_date and pub_date < cutoff:
                continue

            # Clean content HTML
            content_text = BeautifulSoup(content_html, "html.parser").get_text(strip=True)
            excerpt_text = BeautifulSoup(excerpt_html, "html.parser").get_text(strip=True)

            # Extract image from content
            image_url = ""
            content_soup = BeautifulSoup(content_html, "html.parser")
            img = content_soup.find("img")
            if img and img.get("src"):
                image_url = self._normalize_url(img["src"], source_cfg["base_url"])

            reference_links = self._extract_external_reference_links(
                content_html + "\n" + excerpt_html,
                source_cfg["base_url"],
            )

            # Use excerpt if content is too long
            display_content = content_text[:3000] if len(content_text) > 100 else excerpt_text[:2000]

            item = NewsItem(
                source=source_key,
                title=html_lib.unescape(title),
                url=html_lib.unescape(link),
                content=display_content,
                author=source_cfg["name"],
                published_at=pub_date or datetime.now(timezone.utc),
                tags=["china-ai", source_cfg["name"]],
                raw_data={
                    "image_url": image_url,
                    "full_content": content_html,
                    "links": reference_links,
                    "reference_source": source_cfg["name"],
                },
            )
            items.append(item)

        return items

    def _fetch_jina(
        self,
        source_key: str,
        source_cfg: dict,
        max_age_hours: int,
    ) -> list[NewsItem]:
        """通过 jina.ai 代理获取机器之心文章列表和详情。"""
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        max_articles = self.config.get("max_articles_per_source", 50)

        # Step 1: Fetch article list via jina.ai
        try:
            jina_list_url = f"https://r.jina.ai/http://{source_cfg['list_url'].replace('https://', '')}"
            resp = requests.get(
                jina_list_url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                logger.warning(f"Jina proxy failed for list: {resp.status_code}")
                return items
        except Exception as e:
            logger.debug(f"Jina list fetch failed: {e}")
            return items

        # Parse article list - extract article titles and URLs
        list_text = resp.text
        article_urls = self._extract_jiqizhixin_urls(list_text, source_cfg["article_base"])

        # Step 2: Fetch each article
        for article_url in article_urls[:max_articles]:
            try:
                jina_article_url = f"https://r.jina.ai/http://{article_url.replace('https://', '')}"
                resp = requests.get(
                    jina_article_url,
                    timeout=30,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    continue

                article_data = self._parse_jina_article(resp.text, article_url, source_cfg)
                if article_data:
                    pub_date = article_data.get("published_at")
                    if pub_date and pub_date < cutoff:
                        continue

                    item = NewsItem(
                        source=source_key,
                        title=article_data["title"],
                        url=article_data["url"],
                        content=article_data["content"][:3000],
                        author=source_cfg["name"],
                        published_at=pub_date or datetime.now(timezone.utc),
                        tags=["china-ai", source_cfg["name"]],
                        raw_data=article_data.get("raw_data", {}),
                    )
                    items.append(item)
            except Exception as e:
                logger.debug(f"Jina article fetch failed for {article_url}: {e}")
                continue

        return items

    def _extract_jiqizhixin_urls(self, list_text: str, article_base: str) -> list[str]:
        """从机器之心列表页面提取文章URL。"""
        urls = []
        # Pattern 1: Direct URLs in markdown like (https://www.jiqizhixin.com/articles/YYYY-MM-DD-N)
        pattern1 = r'https?://www\.jiqizhixin\.com/articles/\d{4}-\d{2}-\d{2}-\d+'
        matches1 = re.findall(pattern1, list_text)
        urls.extend(matches1)

        # Pattern 2: URLs in image links like ![Image N: img](URL)
        pattern2 = r'!\[Image \d+[^\]]*\]\((https?://image\.jiqizhixin\.com/[^)]+)\)'
        matches2 = re.findall(pattern2, list_text)

        # Pattern 3: Extract article slugs from titles and construct URLs
        # Look for titles followed by "今天" or dates
        lines = list_text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            # Skip empty lines and metadata
            if not line or line.startswith('![') or line.startswith('Title:') or line.startswith('URL Source:') or line.startswith('Markdown Content:'):
                continue
            # If next line is "今天" or a date-like string, this might be a title
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line == '今天' or re.match(r'\d{4}-\d{2}-\d{2}', next_line):
                    # This is likely an article title, but we need the URL
                    pass

        # Deduplicate while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        # If no URLs found, try to construct from known patterns
        if not unique_urls:
            # Try to get today's articles by date pattern
            today = datetime.now()
            for day_offset in range(7):  # Last 7 days
                date = today - timedelta(days=day_offset)
                date_str = date.strftime('%Y-%m-%d')
                # Try common article IDs (1-20)
                for article_id in range(1, 21):
                    url = f"{article_base}/{date_str}-{article_id}"
                    unique_urls.append(url)
                if len(unique_urls) >= 50:
                    break

        return unique_urls[:50]

    def _parse_jina_article(self, text: str, url: str, source_cfg: dict) -> dict | None:
        """解析 jina.ai 返回的文章内容。"""
        lines = text.split('\n')
        title = ""
        content_lines = []
        in_content = False

        for line in lines:
            line = line.strip()
            if line.startswith('Title:'):
                title = line.replace('Title:', '').strip()
                # Remove site suffix
                title = re.sub(r'\s*\|\s*机器之心$', '', title)
            elif line.startswith('URL Source:'):
                continue
            elif line.startswith('Markdown Content:'):
                in_content = True
                continue
            elif in_content:
                content_lines.append(line)

        if not title:
            return None

        content = '\n'.join(content_lines)
        reference_links = self._extract_external_reference_links(content, source_cfg["base_url"])
        image_urls = self._extract_markdown_images(content, source_cfg["base_url"])

        # Try to extract date from URL
        pub_date = None
        date_match = re.search(r'/articles/(\d{4})-(\d{2})-(\d{2})', url)
        if date_match:
            year, month, day = date_match.groups()
            try:
                pub_date = datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
            except ValueError:
                pass

        return {
            "title": title,
            "url": url,
            "content": content,
            "published_at": pub_date,
            "raw_data": {
                "full_content": content,
                "links": reference_links,
                "image_url": image_urls[0] if image_urls else "",
                "image_urls": image_urls,
                "reference_source": source_cfg["name"],
            },
        }

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
        entries = root.findall(".//item") or root.findall(".{http://www.w3.org/2005/Atom}entry")

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
            reference_links = self._extract_external_reference_links(description, source_cfg["base_url"])

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

            raw_data = {"reference_source": source_cfg["name"]}
            if image_url:
                raw_data["image_url"] = image_url
            if reference_links:
                raw_data["links"] = reference_links

            item = NewsItem(
                source=source_key,
                title=html_lib.unescape(title),
                url=html_lib.unescape(link),
                content=desc_clean[:2000],
                author=source_cfg["name"],
                published_at=pub_date or datetime.now(timezone.utc),
                tags=["china-ai", source_cfg["name"]],
                raw_data=raw_data,
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
    def _normalize_url(url: str, base_url: str) -> str:
        if not url:
            return ""
        url = html_lib.unescape(url.strip())
        if url.startswith("//"):
            return "https:" + url
        return urljoin(base_url, url)

    @classmethod
    def _extract_markdown_images(cls, text: str, base_url: str) -> list[str]:
        images = []
        for url in re.findall(r'!\[[^\]]*\]\((https?://[^)\s]+|/[^)\s]+)\)', text or ""):
            normalized = cls._normalize_url(url, base_url)
            if normalized and normalized not in images:
                images.append(normalized)
        return images[:10]

    @classmethod
    def _extract_external_reference_links(cls, content: str, base_url: str) -> list[str]:
        """Extract original-source links from Chinese AI media without treating their copy as source material."""
        if not content:
            return []

        soup = BeautifulSoup(content, "html.parser")
        candidates = []
        for a in soup.find_all("a", href=True):
            href = cls._normalize_url(a["href"], base_url)
            text = a.get_text(" ", strip=True)
            if href and cls._looks_like_reference_link(href, text):
                candidates.append(href)

        plain_text = soup.get_text("\n", strip=True)
        candidates.extend(re.findall(r'https?://[^\s<>"{}|\\^`\[\]）)]+', plain_text))

        result = []
        for url in candidates:
            url = cls._normalize_url(url.rstrip("。.,，；;"), base_url)
            if not url or cls._is_internal_or_asset_url(url):
                continue
            if url not in result:
                result.append(url)
        return result[:8]

    @staticmethod
    def _looks_like_reference_link(url: str, anchor_text: str) -> bool:
        text = (anchor_text or "").lower()
        url_lower = (url or "").lower()
        reference_words = (
            "论文", "paper", "arxiv", "github", "项目", "代码", "地址", "原文",
            "来源", "博客", "blog", "report", "demo", "huggingface", "openreview",
        )
        reference_domains = (
            "arxiv.org", "openreview.net", "github.com", "huggingface.co",
            "paperswithcode.com", "openai.com", "anthropic.com", "deepmind.google",
            "googleblog.com", "research.google", "microsoft.com", "meta.com",
            "nvidia.com", "x.com", "twitter.com", "youtube.com", "youtu.be",
        )
        return any(word in text for word in reference_words) or any(domain in url_lower for domain in reference_domains)

    @staticmethod
    def _is_internal_or_asset_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path.lower()
        except Exception:
            return True

        if not domain:
            return True
        own_domains = ("qbitai.com", "aiera.com.cn", "jiqizhixin.com", "zhidx.com", "leiphone.com")
        if any(d in domain for d in own_domains):
            return True
        if any(domain.startswith(prefix) for prefix in ("image.", "img.", "cdn.", "static.", "assets.")):
            return True
        if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico")):
            return True
        return False

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

    @staticmethod
    def _parse_wp_date(text: str) -> datetime | None:
        """解析 WordPress 日期格式。"""
        if not text:
            return None
        try:
            dt = datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            dt = datetime.strptime(text.strip(), "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        return None
