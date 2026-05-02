# src/pipeline.py
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import json
import re
import hashlib
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from loguru import logger

_BEIJING_TZ = timezone(timedelta(hours=8))
from src.llm.client import LLMClient
from src.llm.prompts import load_prompt
from src.models import NewsItem
from src.tts.engine import TTSEngine
from src.publish.wechat import WeChatPublisher as WechatPublisher
from src.pipeline_cache import (
    load_published_history,
    record_published,
    is_already_published,
    load_image_cache,
    get_cached_image,
    cache_image,
)


def _render_info_card(rows: list[list[str]]) -> str:
    """将表格行转为公众号友好的信息卡片（用 section 模拟）。"""
    if not rows:
        return ""
    parts = []
    for i, cells in enumerate(rows):
        if len(cells) >= 2:
            key = Pipeline._inline_md_to_html(cells[0])
            val = Pipeline._inline_md_to_html(cells[1])
        else:
            key, val = "", Pipeline._inline_md_to_html(cells[0]) if cells else ""
        parts.append(
            f'<span style="color:#888;font-size:13px;">{key}：</span>'
            f'<span style="color:#333;font-size:13px;">{val}</span>'
        )
    return (
        '<section style="background:#f7f8fa;padding:10px 14px;border-radius:8px;margin:10px 0;'
        'border-left:3px solid #1a73e8;">'
        + '&nbsp;&nbsp;|&nbsp;&nbsp;'.join(parts)
        + '</section>'
    )


class Pipeline:
    def __init__(
        self,
        mode: str,
        crawlers: list,
        llm_client: LLMClient,
        publisher: WechatPublisher,
        tts_engine: TTSEngine | None = None,
        verifier=None,
        debug: bool = False,
    ):
        self.mode = mode
        self.crawlers = crawlers
        self.llm = llm_client
        self.publisher = publisher
        self.tts_engine = tts_engine
        self.verifier = verifier
        self.debug = debug
        self.auto_image_generation = os.environ.get("ENABLE_AUTO_IMAGE_GENERATION") == "1"
        self._pub_history = load_published_history()
        self._img_cache = load_image_cache()

    def run(self) -> bool:
        try:
            # 1. Crawl
            logger.info(f"Pipeline [{self.mode}]: crawling...")
            all_items = []
            for crawler in self.crawlers:
                try:
                    items = crawler.fetch()
                    logger.info(f"  {crawler.name}: {len(items)} items")
                    all_items.extend(items)
                except Exception as e:
                    logger.error(f"  {crawler.name} failed: {e}")

            if not all_items:
                logger.warning("No news items fetched, aborting pipeline")
                return False

            # 2. Deduplicate (within run + cross-run history)
            all_items = self._deduplicate(all_items)
            before_history = len(all_items)
            all_items = self._filter_published(all_items)
            filtered_count = before_history - len(all_items)
            if filtered_count > 0:
                logger.info(f"Filtered {filtered_count} already-published items")
            logger.info(f"After dedup: {len(all_items)} items")

            if not all_items:
                logger.warning("All items were already published, aborting")
                return False

            # 2.2 Hard freshness gate for daily and feature runs.
            # Anything older than 24h should not enter selection at all.
            if self.mode in ("daily", "feature"):
                before_fresh = len(all_items)
                all_items = self._filter_fresh_items(all_items, max_hours=24)
                fresh_filtered = before_fresh - len(all_items)
                if fresh_filtered > 0:
                    logger.info(f"Filtered {fresh_filtered} items older than 24h")

                if not all_items:
                    logger.warning("No fresh items left after 24h filter, aborting")
                    return False

            # 2.5 LLM pre-select top items for quality control
            # This happens before media enrichment so we only fetch page assets for
            # the handful of items that can actually make it into the article.
            if len(all_items) > 15:
                logger.info(f"Pre-selecting top 15 from {len(all_items)} items via LLM...")
                all_items = self._select_top_items(all_items, count=15)
                logger.info(f"Pre-selected {len(all_items)} items for article generation")

            self._enrich_items_with_page_media(all_items)

            # 3. LLM generate article
            logger.info("Generating article via LLM...")
            today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
            news_text = self._format_news(all_items)
            template_name = "daily" if self.mode == "daily" else "weekly"

            system_prompt = load_prompt(template_name, date=today, news_content=news_text)
            article_text = ""
            for attempt in range(3):
                article_text = self.llm.generate(system_prompt, news_text)
                # Retry only on empty output; length/structure checks are handled later.
                if article_text and article_text.strip():
                    break
                logger.warning(f"LLM returned incomplete article (attempt {attempt+1}, {len(article_text)} chars), retrying...")

            # Remove AI flavor: review and rewrite to sound more natural
            article_text = self._remove_ai_flavor(article_text)

            # Post-process: split long paragraphs for better readability
            article_text = self._split_long_paragraphs(article_text)

            # Convert markdown-style text to HTML for WeChat
            article_html = self._markdown_to_html(article_text)

            # Truncate if too long for WeChat (limit ~60000 chars)
            if len(article_html) > 60000:
                article_html = article_html[:60000]
                logger.warning("Article truncated to 60000 chars for WeChat compatibility")

            # 4. Generate cover image
            thumb_media_id = ""
            if not self.debug:
                logger.info("Generating cover image...")
                thumb_media_id = self._generate_cover(today, all_items, article_text)

            # 4.5 Insert images for each news section
            article_html = self._insert_section_images(
                article_html,
                all_items,
                article_text,
                article_title=f"AI 科技前沿 | {today}",
            )
            article_html = self._review_and_repair_article_images(
                article_html,
                all_items,
                article_text,
                article_title=f"AI 科技前沿 | {today}",
            )

            title = f"AI 科技前沿 | {today}"
            article_html = self._prepend_article_metadata(article_html, title, thumb_media_id)

            output_dir = Path("output/articles")
            output_dir.mkdir(parents=True, exist_ok=True)
            article_path = output_dir / f"{self.mode}_{today}.html"
            article_path.write_text(article_html, encoding="utf-8")
            logger.info(f"Article staged to {article_path}")
            logger.info(f"Review and draft upload deferred for: {title}")

            # 6. Record published history - DISABLED (only record on manual confirmation)
            # used_titles = self._extract_article_titles(article_html)
            # record_published(used_titles, today, self._pub_history)
            # logger.info(f"Recorded {len(used_titles)} published topics to history")

            # 7. Video generation (if enabled)
            if os.environ.get("ENABLE_VIDEO_GENERATION") == "1" and article_path:
                try:
                    from src.video.pipeline import VideoPipeline
                    video_pipeline = VideoPipeline.from_config()
                    video_result = video_pipeline.generate(article_path)
                    if video_result:
                        logger.info(f"Video generated: {video_result}")
                except Exception as e:
                    logger.warning(f"Video generation skipped: {e}")

            return True

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            return False

    @staticmethod
    def _deduplicate(items: list[NewsItem]) -> list[NewsItem]:
        seen = set()
        result = []
        for item in items:
            normalized = item.title.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                result.append(item)
        return result

    @staticmethod
    def _filter_fresh_items(items: list[NewsItem], max_hours: int = 24) -> list[NewsItem]:
        """Drop items older than the freshness window."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_hours)
        fresh_items = []
        skipped = 0
        for item in items:
            published_at = item.published_at
            if not published_at:
                skipped += 1
                continue
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            if published_at >= cutoff:
                fresh_items.append(item)
            else:
                skipped += 1
        if skipped > 0:
            logger.info(f"Freshness gate dropped {skipped} stale/missing items")
        return fresh_items

    def _filter_published(self, items: list[NewsItem]) -> list[NewsItem]:
        """Filter out items already published in previous runs (keyword match)."""
        result = []
        for item in items:
            if is_already_published(item.title, item.url, self._pub_history):
                logger.debug(f"Skipping already published: {item.title[:50]}")
            else:
                result.append(item)
        return result

    def _generate_cover(self, today: str, items: list[NewsItem], article_text: str) -> str:
        """Use vision model to pick top news images for cover, return thumb_media_id."""
        import requests as http_requests

        # Collect image URLs from news items
        image_urls = []
        for item in items:
            for img in self._collect_item_media(item)["images"][:2]:
                image_urls.append({"url": img, "title": item.title})

        selected_image_url = ""

        if image_urls:
            # Use vision model to pick the best cover image
            pick_prompt = (
                "你是一个微信公众号封面图编辑。以下是多条AI科技新闻及其配图。"
                "请从中选出最适合作为「AI科技前沿」每日快讯封面的一张图片。\n\n"
                "选图标准（按优先级）：\n"
                "1. 优先选择包含图表、数据可视化、模型架构图、技术效果对比图的图片\n"
                "2. 其次选择色彩丰富、视觉冲击力强的图片\n"
                "3. 避免纯文字截图、过于简单的图标或logo\n"
                "4. 图片应能一眼传达「AI/科技」的感觉\n\n"
                "只回复选中图片的编号（从1开始），不要回复其他内容。"
            )
            numbered = "\n".join(f"{i+1}. {img['title']}" for i, img in enumerate(image_urls[:10]))
            try:
                answer = self.llm.generate_with_images(
                    pick_prompt, numbered,
                    [img["url"] for img in image_urls[:10]],
                )
                match = re.search(r'\d+', answer.strip())
                if match:
                    idx = int(match.group()) - 1
                    if 0 <= idx < len(image_urls):
                        selected_image_url = image_urls[idx]["url"]
            except Exception as e:
                logger.warning(f"Vision model cover selection failed: {e}")

        # Try to download the selected image as cover
        if selected_image_url:
            try:
                import html as html_lib
                selected_image_url = html_lib.unescape(selected_image_url)
                resp = http_requests.get(selected_image_url, timeout=15, stream=True,
                                        headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "image" in content_type:
                    img_data = resp.content
                    ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "png"
                    cover_path = Path("output/cover")
                    cover_path.mkdir(parents=True, exist_ok=True)
                    cover_file = cover_path / f"{self.mode}_{today}.{ext}"
                    cover_file.write_bytes(img_data)
                    media_id = self.publisher.upload_thumb(str(cover_file))
                    logger.info(f"Cover image uploaded from news, media_id={media_id}")
                    return media_id
            except Exception as e:
                logger.warning(f"Failed to download selected cover image: {e}")

        # Fallback: use default thumb (skip AI generation in debug mode)
        logger.info("No suitable news image found, using default cover")
        return ""

    def _insert_section_images(
        self, article_html: str, items: list[NewsItem], article_text: str, article_title: str = ""
    ) -> str:
        """Insert media after each section, using title similarity, source media, and generation fallback."""
        h2_pattern = r'<section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e[^"]*">([^<]+)</h2></section>'
        h2_matches = list(re.finditer(h2_pattern, article_html))

        if not h2_matches:
            logger.info("No h2 sections found for image insertion")
            return article_html

        insertions = []
        api_gen_count = 0
        cache_hit_count = 0
        used_media_urls = set()

        for section_index, match in reversed(list(enumerate(h2_matches))):
            section_title = match.group(1).strip()
            section_context = self._section_plain_text(article_html, match.end())

            cached_url = get_cached_image(section_title, self._img_cache, namespace=article_title)
            if cached_url:
                img_html = (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{cached_url}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )
                insertions.append((match.end(), img_html))
                cache_hit_count += 1
                logger.debug(f"Image cache hit: {section_title[:40]}")
                continue

            matched_item = self._match_section_to_item(section_title, section_context, items, section_index)
            matched_media = self._collect_item_media(matched_item) if matched_item else None

            img_html = None
            if matched_media:
                for image_url in matched_media["images"]:
                    if image_url in used_media_urls:
                        continue
                    try:
                        img_html = self._download_and_upload_image(
                            image_url,
                            section_title,
                            cache_namespace=article_title,
                        )
                        if img_html:
                            used_media_urls.add(image_url)
                            break
                    except Exception as e:
                        logger.warning(f"Failed to use news image for '{section_title}': {e}")

                if not img_html:
                    for video_url in matched_media["videos"]:
                        if video_url in used_media_urls:
                            continue
                        try:
                            # Try to download and render video, fallback to link card
                            img_html = self._download_and_render_video(video_url, section_title)
                            if not img_html:
                                # Reddit videos can't be downloaded directly, use link card
                                img_html = self._render_video_link_card(video_url, section_title)
                            if img_html:
                                used_media_urls.add(video_url)
                                break
                        except Exception as e:
                            logger.warning(f"Failed to use news video for '{section_title}': {e}")
                            # Fallback to link card
                            try:
                                img_html = self._render_video_link_card(video_url, section_title)
                                if img_html:
                                    used_media_urls.add(video_url)
                                    break
                            except Exception:
                                pass

            if not img_html and self.auto_image_generation:
                img_html = self._generate_section_image(
                    section_title,
                    section_context or article_text[:600],
                    article_title=article_title,
                )
                if img_html:
                    api_gen_count += 1

            if img_html:
                insertions.append((match.end(), img_html))

        # Apply insertions
        result = article_html
        for pos, img_html in sorted(insertions, reverse=True):
            result = result[:pos] + "\n" + img_html + "\n" + result[pos:]

        logger.info(
            f"Inserted {len(insertions)} section images "
            f"(cache: {cache_hit_count}, api: {api_gen_count})"
        )
        return result

    @staticmethod
    def _section_plain_text(article_html: str, section_start: int, limit: int = 700) -> str:
        next_h2 = article_html.find('<section style="margin:20px 0 8px 0;"><h2', section_start)
        section_html = article_html[section_start: next_h2 if next_h2 != -1 else section_start + limit * 4]
        text = re.sub(r"<[^>]+>", "", section_html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    @staticmethod
    def _match_section_to_item(
        section_title: str,
        section_context: str,
        items: list[NewsItem],
        section_index: int,
    ) -> NewsItem | None:
        if not items:
            return None

        target = f"{section_title} {section_context[:220]}".lower()
        best_item = None
        best_score = 0
        for item in items:
            source_text = f"{item.title} {item.content[:400]}".lower()
            title_score = Pipeline._token_overlap_score(section_title.lower(), item.title.lower()) * 3
            context_score = Pipeline._token_overlap_score(target, source_text)
            score = title_score + context_score
            if score > best_score:
                best_score = score
                best_item = item

        if best_item and best_score >= 2:
            return best_item
        if section_index < len(items):
            return items[section_index]
        return None

    @staticmethod
    def _token_overlap_score(a: str, b: str) -> int:
        token_pattern = r'[a-zA-Z][a-zA-Z0-9_.\-]{2,}|[一-鿿]{2,}'
        tokens_a = set(re.findall(token_pattern, a.lower()))
        tokens_b = set(re.findall(token_pattern, b.lower()))
        stopwords = {
            "这个", "一个", "什么", "为什么", "怎么", "发布", "推出", "模型",
            "系统", "工具", "open", "new", "the", "and", "for", "with",
        }
        tokens_a = {t for t in tokens_a if t not in stopwords}
        tokens_b = {t for t in tokens_b if t not in stopwords}
        return len(tokens_a & tokens_b)

    @staticmethod
    def _collect_item_media(item: NewsItem) -> dict[str, list[str]]:
        raw = item.raw_data or {}
        images = []
        videos = []

        for value in raw.get("reference_images", []) or []:
            if value and value not in images:
                images.append(value)
        for key in ("official_image", "image_url"):
            value = raw.get(key)
            if value and value not in images:
                images.append(value)
        for key in ("image_urls", "benchmark_images"):
            for value in raw.get(key, []) or []:
                if value and value not in images:
                    images.append(value)
        for value in raw.get("comment_images", []) or []:
            if value and value not in images:
                images.append(value)

        for key in ("video_url",):
            value = raw.get(key)
            if value and value not in videos:
                videos.append(value)
        for value in raw.get("reference_video_urls", []) or []:
            if value and value not in videos:
                videos.append(value)
        for value in raw.get("video_urls", []) or []:
            if value and value not in videos:
                videos.append(value)
        for value in raw.get("comment_video_urls", []) or []:
            if value and value not in videos:
                videos.append(value)

        return {"images": images, "videos": videos}

    def _download_and_upload_image(self, image_url: str, title: str, cache_namespace: str = "") -> str | None:
        """Download image from URL, upload to WeChat, cache it."""
        import requests as http_requests
        import html as html_lib

        image_url = html_lib.unescape(image_url)
        resp = http_requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            return None

        ext = self._extension_from_content_type(content_type, "png")
        img_dir = Path("output/images")
        img_dir.mkdir(parents=True, exist_ok=True)
        local_path = img_dir / f"{hashlib.sha1(image_url.encode()).hexdigest()[:12]}.{ext}"
        local_path.write_bytes(resp.content)

        # Validate and convert SVG to PNG if needed
        local_path = self._ensure_valid_image(local_path)

        # Check image dimensions - skip if too small
        try:
            from PIL import Image
            with Image.open(local_path) as img:
                w, h = img.size
                if w < 400 or h < 300:
                    logger.warning(f"Image too small ({w}x{h}), skipping: {image_url}")
                    return None
        except Exception:
            pass

        if self.debug:
            return (
                f'<section style="text-align:center;margin:12px 0;">'
                f'<img src="{local_path.as_posix()}" style="max-width:100%;border-radius:8px;" />'
                f'</section>'
            )

        wechat_url = self.publisher.upload_image(str(local_path))
        if wechat_url:
            cache_image(title, str(local_path), wechat_url, self._img_cache, namespace=cache_namespace or title)
            return (
                f'<section style="text-align:center;margin:12px 0;">'
                f'<img src="{wechat_url}" style="max-width:100%;border-radius:8px;" />'
                f'</section>'
            )
        return None

    @staticmethod
    def _ensure_valid_image(image_path: Path) -> Path:
        """Validate image and convert SVG/WebP to PNG if needed."""
        try:
            from PIL import Image

            # Check if file is actually an SVG (despite extension)
            with open(image_path, 'rb') as f:
                header = f.read(256)
                if b'<svg' in header or b'<?xml' in header:
                    # Convert SVG to PNG
                    import cairosvg

                    png_path = image_path.with_suffix('.png')
                    cairosvg.svg2png(url=str(image_path), write_to=str(png_path))
                    logger.debug(f"Converted SVG to PNG: {png_path}")
                    return png_path

            # Check if file is WebP - WeChat doesn't support it
            with Image.open(image_path) as img:
                img.verify()

            # Re-open to check format after verify
            with Image.open(image_path) as img:
                if img.format == 'WEBP':
                    png_path = image_path.with_suffix('.png')
                    img.save(png_path, 'PNG')
                    logger.debug(f"Converted WebP to PNG: {png_path}")
                    return png_path

            return image_path
        except Exception as e:
            logger.warning(f"Image validation failed for {image_path}: {e}")
            return image_path

    def _download_and_render_video(self, video_url: str, title: str) -> str | None:
        """Download video and render an embeddable video block when possible."""
        import requests as http_requests
        import html as html_lib

        video_url = html_lib.unescape(video_url)

        # Check if this is a Reddit video (v.redd.it) - needs browser recording
        if "v.redd.it" in video_url or "reddit.com/media" in video_url:
            return self._record_reddit_video(video_url, title)

        resp = http_requests.get(video_url, timeout=30, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "video" not in content_type and not video_url.lower().split("?")[0].endswith((".mp4", ".mov", ".webm")):
            return None

        ext = self._extension_from_content_type(content_type, "mp4")
        video_dir = Path("output/videos")
        video_dir.mkdir(parents=True, exist_ok=True)
        local_path = video_dir / f"{hashlib.sha1(video_url.encode()).hexdigest()[:12]}.{ext}"

        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        src = local_path.as_posix()
        return (
            f'<section style="text-align:center;margin:12px 0;" '
            f'data-original-url="{html_lib.escape(video_url, quote=True)}" '
            f'data-section-title="{html_lib.escape(title, quote=True)}">'
            f'<video src="{src}" controls="controls" style="max-width:100%;border-radius:8px;"></video>'
            f'</section>'
        )

    def _record_reddit_video(self, video_url: str, title: str) -> str | None:
        """Record Reddit video using Playwright browser automation."""
        import html as html_lib

        # Extract video ID from URL
        import re
        video_id_match = re.search(r'v\.redd\.it/([a-zA-Z0-9]+)', video_url)
        if not video_id_match:
            return None
        video_id = video_id_match.group(1)

        # Construct Reddit media URL
        media_url = f"https://www.reddit.com/media?url=https%3A%2F%2Fv.redd.it%2F{video_id}"

        video_dir = Path("output/videos")
        video_dir.mkdir(parents=True, exist_ok=True)

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.firefox.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 800, "height": 450},
                    record_video_dir=str(video_dir),
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0"
                )
                page = context.new_page()

                logger.info(f"Recording Reddit video: {video_id}")
                page.goto(media_url, timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(2000)

                # Try to find and play video
                video = page.query_selector('video')
                if video:
                    # Mute and play
                    page.evaluate('document.querySelector("video").muted = true')
                    page.evaluate('document.querySelector("video").play()')

                    # Wait for video duration (max 60s)
                    duration = page.evaluate('document.querySelector("video").duration || 30')
                    record_time = min(duration + 2, 60)
                    page.wait_for_timeout(int(record_time * 1000))
                else:
                    # No video found, record for a few seconds as fallback
                    page.wait_for_timeout(5000)

                context.close()
                browser.close()

            # Find the recorded video file
            webm_files = sorted(video_dir.glob("*.webm"), key=lambda x: x.stat().st_mtime, reverse=True)
            if webm_files:
                webm_path = webm_files[0]

                # Convert webm to mp4 using moviepy
                try:
                    from moviepy import VideoFileClip

                    mp4_path = video_dir / f"reddit_{video_id}.mp4"
                    clip = VideoFileClip(str(webm_path))
                    clip.write_videofile(str(mp4_path), logger=None)
                    clip.close()

                    # Clean up webm
                    webm_path.unlink()

                    logger.info(f"Reddit video recorded and converted: {mp4_path}")

                    return (
                        f'<section style="text-align:center;margin:12px 0;" '
                        f'data-original-url="{html_lib.escape(video_url, quote=True)}" '
                        f'data-section-title="{html_lib.escape(title, quote=True)}">'
                        f'<video src="{mp4_path.as_posix()}" controls="controls" style="max-width:100%;border-radius:8px;"></video>'
                        f'</section>'
                    )
                except Exception as e:
                    logger.warning(f"Failed to convert webm to mp4: {e}")
                    # Fall back to webm
                    return (
                        f'<section style="text-align:center;margin:12px 0;" '
                        f'data-original-url="{html_lib.escape(video_url, quote=True)}" '
                        f'data-section-title="{html_lib.escape(title, quote=True)}">'
                        f'<video src="{webm_path.as_posix()}" controls="controls" style="max-width:100%;border-radius:8px;"></video>'
                        f'</section>'
                    )
        except Exception as e:
            logger.warning(f"Failed to record Reddit video: {e}")
            return None

    @staticmethod
    def _render_video_link_card(video_url: str, title: str) -> str:
        safe_title = Pipeline._inline_md_to_html(title)
        return (
            '<section style="margin:12px 0;padding:12px 14px;border-radius:10px;'
            'background:#f7f8fa;border:1px solid #eceff3;">'
            '<p style="margin:0 0 6px 0;color:#1a1a2e;font-weight:600;">视频素材</p>'
            f'<p style="margin:0;color:#666;font-size:13px;line-height:1.6;">{safe_title} 的原始视频可点开查看：</p>'
            f'<p style="margin:4px 0 0 0;font-size:12px;word-break:break-all;">'
            f'<a href="{video_url}" style="color:#1a73e8;text-decoration:none;">{video_url}</a></p>'
            '</section>'
        )

    @staticmethod
    def _extension_from_content_type(content_type: str, default: str) -> str:
        content_type = (content_type or "").lower()
        if "jpeg" in content_type or "jpg" in content_type:
            return "jpg"
        if "png" in content_type:
            return "png"
        if "webp" in content_type:
            return "webp"
        if "gif" in content_type:
            return "gif"
        if "webm" in content_type:
            return "webm"
        if "quicktime" in content_type:
            return "mov"
        if "mp4" in content_type or "video" in content_type:
            return "mp4"
        return default

    def _generate_section_image(self, title: str, context: str, article_title: str = "") -> str | None:
        """Generate image via API, upload to WeChat, cache it."""
        if not self.auto_image_generation:
            logger.debug(f"Auto image generation disabled, skipping '{title[:40]}'")
            return None
        try:
            from src.image.generator import ImageGenerator
            gen = ImageGenerator()
            img_dir = Path("output/images")
            img_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[^\w]', '_', title[:30])
            img_path = gen.generate_illustration(
                title,
                context,
                output_path=str(img_dir / f"{safe_name}.png"),
                article_title=article_title or title,
            )
            upload_image = getattr(self.publisher, "upload_image", None)
            if not callable(upload_image):
                return (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{img_path.as_posix()}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )

            wechat_url = upload_image(str(img_path))
            if wechat_url:
                cache_image(title, str(img_path), wechat_url, self._img_cache, namespace=article_title or title)
                return (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{wechat_url}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )
        except Exception as e:
            logger.warning(f"Image generation failed for '{title[:40]}': {e}")
        return None

    def _enrich_items_with_page_media(self, items: list[NewsItem]) -> None:
        """Attach media from referenced HF/ModelScope/model pages before LLM writing."""
        for item in items:
            raw = item.raw_data or {}
            item.raw_data = raw

            candidate_urls = [item.url]
            candidate_urls.extend(raw.get("links", []) or [])
            official_url = raw.get("official_url")
            if official_url:
                candidate_urls.append(official_url)

            for url in self._dedupe_urls(candidate_urls):
                if not self._should_fetch_assets_for_item(item, url):
                    continue
                images, tables, videos = self._fetch_page_assets(url)
                if images:
                    existing = raw.get("benchmark_images", []) or []
                    for image in images:
                        if image not in existing:
                            existing.append(image)
                    raw["benchmark_images"] = existing[:8]
                    raw.setdefault("image_url", images[0])
                    if url not in {item.url, official_url}:
                        reference_images = raw.get("reference_images", []) or []
                        for image in images:
                            if image not in reference_images:
                                reference_images.append(image)
                        raw["reference_images"] = reference_images[:8]
                if tables:
                    existing_tables = raw.get("benchmark_tables", []) or []
                    for table in tables:
                        if table not in existing_tables:
                            existing_tables.append(table)
                    raw["benchmark_tables"] = existing_tables[:5]
                if videos:
                    existing_videos = raw.get("video_urls", []) or []
                    for video in videos:
                        if video not in existing_videos:
                            existing_videos.append(video)
                    raw["video_urls"] = existing_videos[:5]
                    if url not in {item.url, official_url}:
                        reference_videos = raw.get("reference_video_urls", []) or []
                        for video in videos:
                            if video not in reference_videos:
                                reference_videos.append(video)
                        raw["reference_video_urls"] = reference_videos[:5]

            self._enrich_twitter_comments(item)

    @staticmethod
    def _dedupe_urls(urls: list[str]) -> list[str]:
        result = []
        for url in urls:
            if url and url.startswith("http") and url not in result:
                result.append(url)
        return result

    @staticmethod
    def _should_fetch_assets_for_item(item: NewsItem, url: str) -> bool:
        text = f"{item.source} {item.title} {item.content} {url}".lower()
        url_lower = url.lower()
        if any(domain in url_lower for domain in ("x.com/", "twitter.com/", "nitter.", "xcancel.com/")):
            return False
        if any(domain in url_lower for domain in ("huggingface.co", "modelscope.cn", "github.com", "arxiv.org")):
            return True
        if any(domain in url_lower for domain in (
            "openai.com", "anthropic.com", "deepmind.google", "googleblog.com",
            "research.google", "microsoft.com", "meta.com", "nvidia.com",
            "intel.com", "amd.com", "qualcomm.com", "apple.com", "amazon.com",
        )):
            if any(path in url_lower for path in (
                "/research", "/news", "/blog", "/paper", "/papers",
                "/publication", "/publications", "/report", "/demo",
            )):
                return True
        return any(keyword in text for keyword in (
            "benchmark", "leaderboard", "eval", "mmlu", "gpqa", "aime",
            "swe-bench", "humaneval", "mistral", "model", "模型", "榜单", "指标",
        ))

    @staticmethod
    def _extract_article_titles(article_html: str) -> list[str]:
        """从文章 HTML 中提取 h2 标题（每条新闻的标题）。"""
        return re.findall(
            r'<h2 style="color:#1a1a2e[^"]*">([^<]+)</h2>', article_html
        )

    def _enrich_twitter_comments(self, item: NewsItem) -> None:
        """Attach top replies/comments for Twitter items."""
        if item.source != "twitter" or not item.url:
            return

        raw = item.raw_data or {}
        if raw.get("comments"):
            return

        try:
            from src.crawlers.twitter_crawler import TwitterCrawler

            comments = TwitterCrawler.fetch_top_comments(
                item.url,
                account=raw.get("account", "") or item.author,
                limit=20,
            )
            if not comments:
                return

            raw["comments"] = comments
            comment_images = []
            comment_videos = []
            for comment in comments:
                for image in comment.get("images", []) or []:
                    if image not in comment_images:
                        comment_images.append(image)
                for video in comment.get("video_urls", []) or []:
                    if video not in comment_videos:
                        comment_videos.append(video)

            if comment_images:
                raw["comment_images"] = comment_images[:8]
            if comment_videos:
                raw["comment_video_urls"] = comment_videos[:5]
        except Exception as e:
            logger.debug(f"Failed to fetch Twitter comments for {item.title[:50]}: {e}")

    def run_feature(self) -> bool:
        """精选 Top 5 新闻，每条单独生成一篇深度文章并发布。"""
        try:
            # 1. Crawl
            logger.info("FeaturePipeline: crawling...")
            all_items = []
            for crawler in self.crawlers:
                try:
                    items = crawler.fetch()
                    logger.info(f"  {crawler.name}: {len(items)} items")
                    all_items.extend(items)
                except Exception as e:
                    logger.error(f"  {crawler.name} failed: {e}")

            if not all_items:
                logger.warning("No news items fetched, aborting")
                return False

            # 2. Deduplicate
            all_items = self._deduplicate(all_items)
            all_items = self._filter_published(all_items)
            logger.info(f"After dedup: {len(all_items)} items for selection")

            if not all_items:
                logger.warning("All items were already published, aborting")
                return False

            # 2.5 Hard freshness gate for feature runs too.
            # Stale items should not even enter the selection pool.
            before_fresh = len(all_items)
            all_items = self._filter_fresh_items(all_items, max_hours=24)
            fresh_filtered = before_fresh - len(all_items)
            if fresh_filtered > 0:
                logger.info(f"Filtered {fresh_filtered} items older than 24h")

            if not all_items:
                logger.warning("No fresh items left after 24h filter, aborting")
                return False

            # 3. LLM select top candidates (选 10 条，留候补)
            candidates = self._select_top_items(all_items, count=10)
            if not candidates:
                logger.warning("LLM failed to select top items")
                return False

            logger.info(f"Selected {len(candidates)} candidates:")
            for i, item in enumerate(candidates, 1):
                logger.info(f"  {i}. {item.title[:60]}")

            # 4. Official verification & freshness check
            verified_items = []
            unverifiable_items = []  # verified but stale/unknown time
            if self.verifier:
                for item in candidates:
                    if len(verified_items) >= 10:
                        break

                    result = self.verifier.verify_official(item)
                    if result["verified"]:
                        # Attach official info to item
                        item.raw_data = item.raw_data or {}
                        if result.get("official_url"):
                            item.raw_data["official_url"] = result["official_url"]
                        if result.get("official_image"):
                            item.raw_data["official_image"] = result["official_image"]

                        fresh = self.verifier.check_freshness(
                            result.get("publish_time", ""),
                            item_published_at=item.published_at,
                        )
                        if fresh:
                            verified_items.append(item)
                            logger.info(f"  VERIFIED (fresh): {item.title[:50]}")
                        else:
                            unverifiable_items.append(item)
                            logger.info(f"  STALE (kept as backup): {item.title[:50]}")
                    else:
                        logger.info(f"  SKIP (unverified): {item.title[:50]}")

                if not verified_items:
                    logger.warning("No verified items, using top 10 candidates as fallback")
                    verified_items = candidates[:10]
            else:
                verified_items = candidates[:10]

            logger.info(f"Verified: {len(verified_items)} items for staging")
            self._enrich_items_with_page_media(verified_items[:10])

            # 5. Generate & publish each
            today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
            output_dir = Path("output/articles")
            output_dir.mkdir(parents=True, exist_ok=True)

            published_count = 0
            for i, item in enumerate(verified_items[:10], 1):
                logger.info(f"Generating article {i}/{len(verified_items[:10])}: {item.title[:50]}")

                # Generate Chinese title first
                chinese_title = self._generate_chinese_title(item)
                logger.info(f"  Title: {chinese_title}")

                article_html = self._generate_single_article(item, today)

                # Truncate if too long
                if len(article_html) > 60000:
                    article_html = article_html[:60000]

                # Cover image: priority official_image > news image > default
                thumb_media_id = ""
                if not self.debug:
                    thumb_media_id = self._get_cover_for_item(item, today, i)

                # Use generated Chinese title
                clean_title = chinese_title
                if len(clean_title) > 60:
                    clean_title = clean_title[:57] + "..."

                # Save article with metadata for later draft upload
                article_html = self._prepend_article_metadata(article_html, clean_title, thumb_media_id)
                article_path = output_dir / f"feature_{today}_{i}.html"
                article_path.write_text(article_html, encoding="utf-8")

                logger.info(f"Article {i} staged to {article_path}")
                published_count += 1

            logger.info(f"FeaturePipeline done: {published_count}/{len(verified_items[:10])} articles staged")
            return published_count > 0

        except Exception as e:
            logger.error(f"FeaturePipeline failed: {e}")
            return False

    def _select_top_items(self, items: list[NewsItem], count: int = 5) -> list[NewsItem]:
        """LLM 筛选最有价值的新闻。"""
        news_list = ""
        for i, item in enumerate(items, 1):
            news_list += f"{i}. [{item.source}] {item.title}\n"

        selector_prompt = load_prompt("selector", news_list=news_list)
        try:
            answer = self.llm.generate(selector_prompt, news_list)
        except Exception as e:
            logger.error(f"LLM selection failed: {e}")
            return items[:count]

        # Parse indices from answer
        indices = []
        for line in answer.strip().split("\n"):
            line = line.strip()
            match = re.match(r'^(\d+)', line)
            if match:
                idx = int(match.group(1))
                if 1 <= idx <= len(items):
                    indices.append(idx - 1)

        if not indices:
            logger.warning("Failed to parse LLM selection, using first N items")
            return items[:count]

        selected = [items[i] for i in indices[:count]]
        return selected

    def _generate_single_article(self, item: NewsItem, date: str) -> str:
        """为单条新闻生成深度文章 HTML，并在段落间插入审核过的配图。"""

        # Fetch original and referenced pages for screenshots, charts, tables and demos.
        raw = item.raw_data or {}
        candidate_urls = [item.url]
        candidate_urls.extend(raw.get("links", []) or [])
        official_url = raw.get("official_url")
        if official_url:
            candidate_urls.append(official_url)

        page_images, page_tables, page_videos = [], [], []
        page_texts = []
        for url in self._dedupe_urls(candidate_urls):
            if not self._should_fetch_assets_for_item(item, url):
                continue
            page_text = self._fetch_page_text_excerpt(url)
            if page_text and page_text not in page_texts:
                page_texts.append(page_text)
            images, tables, videos = self._fetch_page_assets(url)
            for image in images:
                if image not in page_images:
                    page_images.append(image)
            for table in tables:
                if table not in page_tables:
                    page_tables.append(table)
            for video in videos:
                if video not in page_videos:
                    page_videos.append(video)

        self._enrich_twitter_comments(item)

        raw = item.raw_data or {}
        if page_images:
            existing_images = raw.get("benchmark_images", []) or []
            for image in page_images:
                if image not in existing_images:
                    existing_images.append(image)
            raw["benchmark_images"] = existing_images[:10]
            raw.setdefault("image_url", page_images[0])
        if page_tables:
            existing_tables = raw.get("benchmark_tables", []) or []
            for table in page_tables:
                if table not in existing_tables:
                    existing_tables.append(table)
            raw["benchmark_tables"] = existing_tables[:5]
        if page_videos:
            existing_videos = raw.get("video_urls", []) or []
            for video in page_videos:
                if video not in existing_videos:
                    existing_videos.append(video)
            raw["video_urls"] = existing_videos[:5]

        comment_text = self._format_comments(raw.get("comments", []), limit=20)

        # Web search for latest context to prevent outdated claims
        search_context = self._fetch_search_context(item.title)

        # Cross-company reactions: search for responses from competitors/peers
        cross_reactions = self._fetch_cross_company_reactions(item)
        if cross_reactions:
            logger.info(f"  Found {len(cross_reactions)} cross-company reactions")
            # De-duplicate: skip reactions that are already in search_context or item content
            existing_text = (search_context or "") + item.content + item.title
            cross_reactions = [
                r for r in cross_reactions
                if r.get("text", "")[:100] not in existing_text
            ]

        feature_prompt = load_prompt(
            "feature",
            title=item.title,
            source=item.source,
            author=item.author,
            date=item.published_at.strftime("%Y-%m-%d %H:%M"),
            content=item.content[:3000],
            url=item.url,
        )
        # Append search context and page assets to prompt
        if search_context:
            feature_prompt += (
                "\n\n---\n"
                "【事实核实信息】以下是关于此话题的最新搜索结果。"
                "你必须在写作时据此核实事实，特别注意：\n"
                "1. 只采用可核验来源里的版本号、价格、跑分和发布日期\n"
                "2. 搜索结果和原素材冲突时，以官方公告、论文、代码仓库为先\n"
                "3. 不要编造不存在的版本号、排名或人物观点\n"
                f"搜索结果：\n{search_context}"
            )
        if page_images:
            feature_prompt += f"\n\n---\n原文中包含以下图片，请在合适位置引用描述：\n" + "\n".join(f"- {u}" for u in page_images[:5])
        if page_texts:
            feature_prompt += (
                "\n\n---\n"
                "【原始页面正文摘要】以下内容来自官方公告、参考链接或演示页。"
                "请优先用这些一手信息展开案例、功能细节和实测过程：\n"
                + "\n\n".join(page_texts[:3])
            )
        if page_tables:
            feature_prompt += f"\n\n---\n原文中包含以下表格数据，请在文中转述：\n" + "\n".join(page_tables[:3])
        if page_videos:
            item.raw_data = item.raw_data or {}
            item.raw_data["video_urls"] = list(dict.fromkeys((item.raw_data.get("video_urls", []) or []) + page_videos))[:5]
        if cross_reactions:
            feature_prompt += (
                "\n\n---\n"
                "【行业反应】以下是竞争对手、同行或相关高管对此事的公开回应。"
                "请在文章中适当引用，增加报道的立体感和行业视角：\n"
                + "\n".join(
                    f"- [{r.get('company', '未知')}] {r.get('source', '')}: {r.get('text', '')[:300]}"
                    for r in cross_reactions[:5]
                )
            )

        if comment_text:
            feature_prompt += (
                "\n\n---\n"
                "【热门评论】以下评论仅供参考，官方回复优先。若与正文不相关，可不引用。"
                "评论区图表与正文配图同权重，按内容相关性决定是否使用。\n"
                f"{comment_text}"
            )

        # Generate with retry on empty result
        article_text = ""
        for attempt in range(2):
            article_text = self.llm.generate(feature_prompt, item.content[:2000])
            if article_text and len(article_text.strip()) > 100:
                break
            logger.warning(f"LLM returned empty/short article (attempt {attempt+1}), retrying...")

        # Remove AI flavor: review and rewrite to sound more natural
        article_text = self._remove_ai_flavor(article_text)

        article_html = self._markdown_to_html(article_text)

        # Append reference links section
        ref_links = []
        if item.url:
            ref_links.append(("原文链接", item.url))
        official_url = (item.raw_data or {}).get("official_url", "")
        if official_url and official_url != item.url:
            ref_links.append(("官方来源", official_url))
        for ref_url in (item.raw_data or {}).get("links", []) or []:
            if ref_url and ref_url not in {item.url, official_url}:
                ref_links.append(("参考链接", ref_url))
        if ref_links:
            ref_parts = [
                '<section style="margin:24px 0 8px 0;padding-top:8px;border-top:1px solid #eee;">',
            ]
            for label, url in ref_links:
                ref_parts.append(
                    f'<p style="color:#888;font-size:13px;margin:6px 0;line-height:1.6;">'
                    f'<a href="{url}" style="color:#888;text-decoration:none;word-break:break-all;">{url}</a></p>'
                )
            ref_parts.append('</section>')
            article_html += "\n" + "\n".join(ref_parts)

        # Capture and insert social media screenshots (Twitter, Reddit)
        article_html = self._insert_social_screenshots(article_html, item)

        # Collect candidate images: official_image > source images > benchmark charts
        candidates = self._collect_item_media(item)["images"]

        # Also collect videos for insertion
        videos = self._collect_item_media(item)["videos"]

        # Upload candidates to WeChat and get permanent URLs
        uploaded = []
        for img_url in candidates:
            try:
                img_html = self._download_and_upload_image(img_url, item.title)
                if img_html:
                    m = re.search(r'src="([^"]+)"', img_html)
                    if m:
                        uploaded.append(m.group(1))
            except Exception as e:
                logger.debug(f"Failed to upload candidate image: {e}")

        # Find h2 sections first
        h2_pattern = r'<section style="margin:20px[^"]*"><h2[^>]*>[^<]+</h2></section>'
        h2_matches = list(re.finditer(h2_pattern, article_html))

        # If no candidate images, skip generation — use news source images only
        if not uploaded and h2_matches and not self.debug:
            pass  # No API image generation

        if not uploaded or not h2_matches:
            return article_html

        # Insert images after each h2 section, verified by vision model
        img_idx = 0
        insertions = []
        for match in h2_matches:
            if img_idx >= len(uploaded):
                break

            after_h2 = article_html[match.end():]
            text_after = re.sub(r'<[^>]+>', '', after_h2[:500]).strip()[:300]
            img_url = uploaded[img_idx]

            # In debug mode, insert without vision verification
            should_insert = True
            if not self.debug:
                should_insert = self._verify_image_for_section(img_url, text_after)

            if should_insert:
                img_html = (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{img_url}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )
                insertions.append((match.end(), img_html))
                img_idx += 1
            else:
                if img_idx + 1 < len(uploaded):
                    next_url = uploaded[img_idx + 1]
                    next_ok = True
                    if not self.debug:
                        next_ok = self._verify_image_for_section(next_url, text_after)
                    if next_ok:
                        img_html = (
                            f'<section style="text-align:center;margin:12px 0;">'
                            f'<img src="{next_url}" style="max-width:100%;border-radius:8px;" />'
                            f'</section>'
                        )
                        insertions.append((match.end(), img_html))
                        img_idx += 2

        # Apply insertions in reverse order
        for pos, img_html in sorted(insertions, reverse=True):
            article_html = article_html[:pos] + "\n" + img_html + "\n" + article_html[pos:]

        if insertions:
            logger.info(f"Inserted {len(insertions)} verified images in feature article")
        elif uploaded and h2_matches:
            # Hard fallback: if the vision gate rejects every candidate, keep one
            # official/source image instead of shipping a text-only article.
            fallback_html = (
                f'<section style="text-align:center;margin:12px 0;">'
                f'<img src="{uploaded[0]}" style="max-width:100%;border-radius:8px;" />'
                f'</section>'
            )
            first_pos = h2_matches[0].end()
            article_html = article_html[:first_pos] + "\n" + fallback_html + "\n" + article_html[first_pos:]
            logger.info("Inserted 1 fallback image in feature article")

        # Insert videos if available (after images)
        if videos:
            for video_url in videos[:1]:  # Max 1 video per article
                try:
                    video_html = self._download_and_render_video(video_url, item.title)
                    if video_html:
                        # Insert before reference links section
                        ref_section = article_html.find('<section style="margin:24px')
                        if ref_section > 0:
                            article_html = article_html[:ref_section] + "\n" + video_html + "\n" + article_html[ref_section:]
                        else:
                            article_html += "\n" + video_html
                        logger.info(f"Inserted video in feature article: {video_url[:50]}...")
                        break
                except Exception as e:
                    logger.warning(f"Failed to insert video: {e}")

        article_html = self._review_and_repair_article_images(
            article_html,
            [item],
            article_text,
            article_title=item.title,
        )
        return article_html

    def _insert_twitter_screenshots(self, article_html: str, item: NewsItem) -> str:
        """Capture Twitter screenshots and insert them into article HTML.

        Inserts screenshots after relevant sections or at the beginning of the article.
        """
        try:
            from src.utils.twitter_screenshot import TwitterScreenshot

            screenshot = TwitterScreenshot()

            # Capture main tweet screenshot
            tweet_url = item.url
            if not tweet_url or ("twitter.com" not in tweet_url and "x.com" not in tweet_url):
                return article_html

            screenshot_path = screenshot.capture(tweet_url)
            if not screenshot_path:
                return article_html

            # Upload to WeChat
            upload_image = getattr(self.publisher, "upload_image", None)
            if not callable(upload_image):
                # In debug mode or no publisher, use local path
                img_html = (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{screenshot_path.as_posix()}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )
                # Insert before first h2 section (after intro)
                first_h2 = article_html.find('<section style="margin:20px')
                if first_h2 > 0:
                    article_html = article_html[:first_h2] + img_html + "\n\n" + article_html[first_h2:]
                else:
                    first_p_end = article_html.find("</p>")
                    if first_p_end > 0:
                        insert_pos = first_p_end + 4
                        article_html = article_html[:insert_pos] + "\n\n" + img_html + article_html[insert_pos:]
                    else:
                        article_html = img_html + "\n\n" + article_html
                return article_html

            wechat_url = upload_image(str(screenshot_path))
            if wechat_url:
                img_html = (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{wechat_url}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )
                # Insert after the first "intro" paragraph (before first h2 section)
                # Find first h2 section and insert before it
                first_h2 = article_html.find('<section style="margin:20px')
                if first_h2 > 0:
                    # Insert before first h2
                    article_html = article_html[:first_h2] + img_html + "\n\n" + article_html[first_h2:]
                else:
                    # Fallback: insert after first paragraph
                    first_p_end = article_html.find("</p>")
                    if first_p_end > 0:
                        insert_pos = first_p_end + 4
                        article_html = article_html[:insert_pos] + "\n\n" + img_html + article_html[insert_pos:]
                    else:
                        article_html = img_html + "\n\n" + article_html
                logger.info(f"Inserted Twitter screenshot: {wechat_url}")

            # Also capture screenshots from referenced tweet links in raw_data
            raw = item.raw_data or {}
            links = raw.get("links", []) or []
            tweet_urls = [
                url for url in links
                if "twitter.com" in url or "x.com" in url
            ]

            for ref_url in tweet_urls[:2]:  # Max 2 additional screenshots
                ref_path = screenshot.capture(ref_url)
                if ref_path:
                    ref_wechat_url = upload_image(str(ref_path))
                    if ref_wechat_url:
                        ref_img_html = (
                            f'<section style="text-align:center;margin:12px 0;">'
                            f'<img src="{ref_wechat_url}" style="max-width:100%;border-radius:8px;" />'
                            f'</section>'
                        )
                        # Insert before reference links section
                        ref_section = article_html.find('<section style="margin:24px')
                        if ref_section > 0:
                            article_html = article_html[:ref_section] + ref_img_html + "\n\n" + article_html[ref_section:]
                        else:
                            article_html += "\n\n" + ref_img_html

        except Exception as e:
            logger.warning(f"Failed to insert Twitter screenshots: {e}")

        return article_html

    def _insert_social_screenshots(self, article_html: str, item: NewsItem) -> str:
        """Capture and insert screenshots from social media sources (Reddit, Twitter).

        Detects references to Reddit posts or tweets in article text and inserts
        screenshots with Chinese translation for credibility.
        """
        try:
            upload_image = getattr(self.publisher, "upload_image", None)
            if not callable(upload_image):
                # In debug mode or no publisher, use local paths
                upload_image = None

            # Find Reddit references in article text
            reddit_pattern = r'Reddit[^,.]*(?:帖主|用户|网友|帖子|讨论|评论)[^,.]*(?:记录|提到|分享|发布|说|写道)'
            has_reddit_ref = bool(re.search(reddit_pattern, article_html, re.IGNORECASE))

            # Find any Reddit URLs in item links
            raw = item.raw_data or {}
            links = raw.get("links", []) or []
            reddit_urls = [url for url in links if "reddit.com" in url]

            # Also check if item URL itself is Reddit
            if "reddit.com" in item.url:
                reddit_urls.insert(0, item.url)

            if reddit_urls:
                from src.utils.reddit_screenshot import RedditScreenshot
                screenshot = RedditScreenshot()

                for reddit_url in reddit_urls[:1]:  # Max 1 Reddit screenshot
                    screenshot_path = screenshot.capture(reddit_url)
                    if screenshot_path:
                        # Add caption with source info
                        caption_html = (
                            '<section style="margin:12px 0;padding:10px 14px;'
                            'background:#f7f8fa;border-radius:8px;border-left:3px solid #ff4500;">'
                            '<p style="margin:0;color:#666;font-size:13px;line-height:1.6;">'
                            '<strong style="color:#ff4500;">Reddit 原帖截图</strong> '
                            '（来源：r/LocalLLaMA 社区讨论）'
                            '</p></section>'
                        )

                        if upload_image:
                            wechat_url = upload_image(str(screenshot_path))
                            if wechat_url:
                                img_html = (
                                    f'<section style="text-align:center;margin:12px 0;">'
                                    f'<img src="{wechat_url}" style="max-width:100%;border-radius:8px;" />'
                                    f'</section>'
                                )
                                # Insert before reference links section
                                ref_section = article_html.find('<section style="margin:24px')
                                if ref_section > 0:
                                    insert_html = img_html + "\n\n" + caption_html + "\n\n"
                                    article_html = article_html[:ref_section] + insert_html + article_html[ref_section:]
                                else:
                                    article_html += "\n\n" + img_html + "\n\n" + caption_html
                                logger.info(f"Inserted Reddit screenshot: {wechat_url}")
                        else:
                            # Debug mode - use local path
                            img_html = (
                                f'<section style="text-align:center;margin:12px 0;">'
                                f'<img src="{screenshot_path.as_posix()}" style="max-width:100%;border-radius:8px;" />'
                                f'</section>'
                            )
                            ref_section = article_html.find('<section style="margin:24px')
                            if ref_section > 0:
                                insert_html = img_html + "\n\n" + caption_html + "\n\n"
                                article_html = article_html[:ref_section] + insert_html + article_html[ref_section:]
                            else:
                                article_html += "\n\n" + img_html + "\n\n" + caption_html

            # Twitter screenshots (existing logic, now called from here)
            if item.source == "twitter" or "twitter.com" in item.url or "x.com" in item.url:
                article_html = self._insert_twitter_screenshots(article_html, item)

        except Exception as e:
            logger.warning(f"Failed to insert social screenshots: {e}")

        return article_html

    def _review_and_repair_article_images(
        self,
        article_html: str,
        items: list[NewsItem],
        article_text: str,
        article_title: str = "",
    ) -> str:
        """Second-pass review for inserted images before draft creation."""
        image_pattern = re.compile(
            r'(<section style="text-align:center;margin:12px 0;">'
            r'\s*<img src="([^"]+)" style="max-width:100%;border-radius:8px;" />'
            r'\s*</section>)'
        )
        matches = list(image_pattern.finditer(article_html))
        if not matches:
            return article_html

        rebuilt = []
        last_end = 0
        replaced = 0
        used_urls = set()

        for match in matches:
            rebuilt.append(article_html[last_end:match.start()])
            image_block = match.group(1)
            image_url = match.group(2)
            used_urls.add(image_url)

            section_match = self._find_last_section_heading(article_html, match.start())
            if section_match:
                section_title = section_match.group(1).strip()
                section_context = self._section_plain_text(article_html, section_match.end())
            else:
                section_title = article_title or "文章配图"
                section_context = article_text[:600]

            keep = True
            if not self.debug:
                keep = self._review_article_image(image_url, section_title, section_context, article_title)

            if keep:
                rebuilt.append(image_block)
            else:
                replacement = self._replace_section_image_after_review(
                    section_title=section_title,
                    section_context=section_context,
                    items=items,
                    article_text=article_text,
                    article_title=article_title,
                    avoid_urls=used_urls,
                )
                if replacement:
                    rebuilt.append(replacement)
                    replaced += 1
                else:
                    rebuilt.append(image_block)

            last_end = match.end()

        rebuilt.append(article_html[last_end:])
        if replaced > 0:
            logger.info(f"Re-reviewed article images: replaced {replaced} low-value images")
        return "".join(rebuilt)

    @staticmethod
    def _find_last_section_heading(article_html: str, upto: int):
        h2_pattern = r'<section style="margin:20px[^"]*"><h2[^>]*>([^<]+)</h2></section>'
        last_match = None
        for match in re.finditer(h2_pattern, article_html[:upto]):
            last_match = match
        return last_match

    def _review_article_image(
        self,
        image_url: str,
        section_title: str,
        section_context: str,
        article_title: str = "",
    ) -> bool:
        """Ask the vision model whether a draft image should stay."""
        try:
            prompt = (
                "你是微信公众号的最终审稿人，负责二次审查正文配图。\n"
                "请判断这张图片是否值得保留。\n\n"
                "保留标准：\n"
                "1. 图片必须和段落主题高度相关\n"
                "2. 清晰的官方产品截图、演示截图、图表、代码界面、流程图、GIF 首帧都可以保留\n"
                "3. 只有低清、无关、logo、头像、装饰图、来源媒体封面截图才拒绝\n"
                "4. 如果图片能让读者理解产品能力或实测过程，应保留\n\n"
                f"文章标题：{article_title}\n"
                f"小节标题：{section_title}\n"
                f"段落内容：{section_context[:240]}\n\n"
                "只回复 YES 或 NO，不要解释。"
            )
            answer = self.llm.generate_with_images(
                prompt,
                f"{section_title}\n{section_context[:180]}",
                [image_url],
            )
            return answer.strip().upper().startswith("YES")
        except Exception as e:
            logger.debug(f"Article image re-review failed, will replace: {e}")
            return False

    def _replace_section_image_after_review(
        self,
        section_title: str,
        section_context: str,
        items: list[NewsItem],
        article_text: str,
        article_title: str = "",
        avoid_urls: set[str] | None = None,
    ) -> str | None:
        """Try to swap a rejected image with a better one or a generated illustration."""
        avoid_urls = avoid_urls or set()
        matched_item = self._match_section_to_item(section_title, section_context, items, 0)

        if matched_item:
            media = self._collect_item_media(matched_item)
            for image_url in media["images"]:
                if image_url in avoid_urls:
                    continue
                try:
                    img_html = self._download_and_upload_image(
                        image_url,
                        section_title,
                        cache_namespace=article_title,
                    )
                    if img_html:
                        return img_html
                except Exception as e:
                    logger.debug(f"Replacement image failed for '{section_title[:40]}': {e}")

        if self.auto_image_generation:
            return self._generate_section_image(
                section_title,
                section_context or article_text[:600],
                article_title=article_title or section_title,
            )
        return None

    @staticmethod
    def _prepend_article_metadata(article_html: str, title: str, thumb_media_id: str = "") -> str:
        meta = [f"<!-- ARTICLE_TITLE: {title} -->"]
        if thumb_media_id:
            meta.append(f"<!-- THUMB_MEDIA_ID: {thumb_media_id} -->")
        return "\n".join(meta) + "\n" + article_html

    def _fetch_page_assets(self, url: str) -> tuple[list[str], list[str], list[str]]:
        """从原始 URL 抓取图片和表格数据。"""
        images = []
        tables = []
        videos = []
        if not url:
            return images, tables, videos
        try:
            import html as html_lib
            from bs4 import BeautifulSoup
            resp = self._fetch_page_response(url, timeout=20)
            if resp.status_code != 200:
                return images, tables, videos

            soup = BeautifulSoup(resp.text, "html.parser")

            for meta_selector in (
                {"property": "og:image"},
                {"name": "twitter:image"},
            ):
                meta = soup.find("meta", attrs=meta_selector)
                content = meta.get("content", "") if meta else ""
                if content:
                    content = self._normalize_page_asset_url(url, html_lib.unescape(content))
                    if content not in images:
                        images.append(content)

            # Collect meaningful images (skip logos, icons, avatars)
            # Also check width/height attributes to filter out small thumbnails
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("data-original") or img.get("data-lazy-src") or img.get("src", "")
                if not src or src.startswith("data:"):
                    continue
                alt = img.get("alt", "").lower()

                # Skip small images based on explicit dimensions
                width = img.get("width", "")
                height = img.get("height", "")
                if width and height:
                    try:
                        w = int(width)
                        h = int(height)
                        if w < 200 or h < 200:  # Skip thumbnails smaller than 200px
                            continue
                    except ValueError:
                        pass

                if any(skip in (src + alt).lower() for skip in (
                    "logo", "icon", "avatar", "profile", "badge", "1x1", "pixel",
                    "artcard-", "card image", "thumbnail", "thumb", "small",
                    "favicon", "emoji", "smiley", "sprite",
                )):
                    continue
                src = self._normalize_page_asset_url(url, html_lib.unescape(src))
                if not src.startswith("http"):
                    continue
                if src not in images:
                    images.append(src)

            for video in soup.find_all(["video", "source"]):
                src = video.get("src", "")
                if not src:
                    continue
                src = urljoin(url, src)
                if src.startswith("http") and src not in videos:
                    videos.append(src)
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a["href"])
                href_lower = href.lower().split("?")[0]
                if href_lower.endswith((".mp4", ".mov", ".webm")) and href not in videos:
                    videos.append(href)

            # Collect table data as text
            for table in soup.find_all("table")[:3]:
                rows = []
                for tr in table.find_all("tr")[:10]:
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    tables.append("\n".join(rows))

            if len(tables) < 3:
                page_text = soup.get_text("\n", strip=True)
                lines = [line for line in page_text.splitlines() if line.count("|") >= 2]
                current = []
                for line in lines:
                    current.append(line)
                    if len(current) >= 10:
                        break
                if len(current) >= 2:
                    tables.append("\n".join(current[:10]))

        except Exception as e:
            logger.debug(f"Failed to fetch page assets from {url}: {e}")
        return images[:10], tables[:5], videos[:5]

    @staticmethod
    def _fetch_page_response(url: str, timeout: int = 15):
        """Fetch a source page, using browser TLS fingerprint fallback when normal requests is challenged."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        import requests as http_requests

        resp = http_requests.get(url, timeout=timeout, headers=headers)
        challenged = (
            resp.status_code in {403, 429}
            or "cf-mitigated" in {k.lower(): v for k, v in resp.headers.items()}
            or "cloudflare" in resp.text[:2000].lower()
        )
        if not challenged:
            return resp

        try:
            from curl_cffi import requests as curl_requests

            return curl_requests.get(
                url,
                timeout=timeout,
                headers=headers,
                impersonate=os.environ.get("CURL_CFFI_IMPERSONATE", "chrome124"),
            )
        except Exception as e:
            logger.debug(f"curl_cffi page fetch fallback failed for {url}: {e}")
            return resp

    @staticmethod
    def _normalize_page_asset_url(page_url: str, asset_url: str) -> str:
        absolute = urljoin(page_url, asset_url)
        parsed = urlparse(absolute)
        if parsed.path.endswith("/_next/image"):
            target = parse_qs(parsed.query).get("url", [""])[0]
            if target:
                return unquote(target)
        return absolute

    def _fetch_search_context(self, title: str) -> str:
        """通过 web 搜索获取最新上下文，避免文章引用过时信息。"""
        try:
            from src.verifier import NewsVerifier
            # Clean title for search
            clean = re.sub(r'^(Pinned:\s*|RT\s+@\w+:\s*|RT by @\w+:\s*)', '', title)
            results = NewsVerifier._web_search(clean[:80], max_results=3)
            if not results:
                return ""
            parts = []
            for r in results[:3]:
                snippet = r.get("snippet", "")
                if snippet:
                    parts.append(f"- {snippet}")
            return "\n".join(parts)
        except Exception as e:
            logger.debug(f"Search context fetch failed: {e}")
            return ""

    def _fetch_page_text_excerpt(self, url: str, max_chars: int = 1800) -> str:
        if not url or any(domain in url.lower() for domain in ("x.com/", "twitter.com/", "nitter.")):
            return ""
        try:
            from bs4 import BeautifulSoup

            resp = self._fetch_page_response(url, timeout=20)
            text = ""
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                soup = BeautifulSoup(resp.text, "html.parser")
                for node in soup.find_all(["script", "style", "noscript"]):
                    node.decompose()
                text = soup.get_text("\n", strip=True)

            if not text or len(text) < 300:
                import requests as http_requests
                jina_url = "https://r.jina.ai/http://" + url.replace("https://", "").replace("http://", "")
                resp = http_requests.get(jina_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    text = resp.text

            text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
            if not text:
                return ""
            return f"来源：{url}\n{text[:max_chars]}"
        except Exception as e:
            logger.debug(f"Failed to fetch page text from {url}: {e}")
            return ""

    def _remove_ai_flavor(self, article_text: str) -> str:
        """审核并去除文章中的 AI 味，让语言更自然、更有吸引力、更有内涵。"""
        if not article_text or len(article_text.strip()) < 50:
            return article_text

        review_prompt = """你是一位资深中文编辑，负责给科技文章"去AI味"并提升可读性和吸引力。

## 核心目标
让文章读起来像是一个有阅历、有观点的朋友在聊天，而不是AI在写报告。

## 具体任务（按优先级排序）

### 1. 去除AI腔（最高优先级）
- 删除或改写：「值得注意的是」「总的来说」「可以说」「未来可期」「让我们拭目以待」「毋庸置疑」「时间会给出答案」「这背后的逻辑是」
- 删除或改写：「随着...的发展」「在...的背景下」「从...的角度来看」等公文式开头
- 删除或改写：连续三段使用同一种句式开头（如都以"XX公司宣布..."开头）

### 2. 增加"人味"和吸引力
- **把抽象概念翻译成生活语言**：不说"参数高效微调提升了模型适应性"，说"就像给AI打疫苗，不用重塑整个身体，只训练它识别特定任务"
- **增加具体场景**：每个技术点后面加一个"想象一下..."或"比如..."的场景
- **增加观点态度**：不要骑墙，可以温和但要有立场。把"让我们拭目以待"改成"这个方向看起来是对的，但还有几个问题没解决"
- **增加幽默感**：适度吐槽，对事不对人。如"OpenAI这次定价，让隔壁开源模型的免费策略显得格外顺眼"

### 3. 提升信息密度和内涵
- **删除空洞评价**：「意义重大」「影响深远」「值得关注」「具有里程碑意义」——要么换成具体说明，要么删除
- **保留并强化**：具体案例、实测数据、真实引用、关键细节
- **增加"翻译成人话"段落**：用一句话让不懂技术的人明白发生了什么
- **增加"对你意味着什么"**：每个技术点都要回答这个问题

### 4. 优化节奏和结构
- **每段不超过80字**
- **一段只讲一个意思**
- **多用短句，少用从句**
- **段落之间留空行**
- 段落间要有逻辑推进，不要并列堆砌
- 开头要有钩子，结尾要有余韵（开放式问题或行动号召）
- **如果原文有一段超过80字，考虑拆成多段**

### 5. 事实准确性（铁律）
- 保持所有事实不变，不添加未确认的信息
- 不编造人物观点、数据、版本号
- 如果原文有不确定表述，保留"据...称"等限定词

## 输出要求
- 只输出修改后的文章全文
- 保留 Markdown 格式（## 标题、**加粗**等）
- 不要解释改了什么

---文章开始---
"""
        try:
            # Use lower temperature for review to ensure factual consistency
            result = self.llm.generate(review_prompt, article_text, temperature=0.3)
            if result and len(result.strip()) > len(article_text.strip()) * 0.5:
                logger.info("AI flavor review completed")
                return result
            logger.warning("AI flavor review returned short result, keeping original")
        except Exception as e:
            logger.warning(f"AI flavor review failed: {e}")
        return article_text

    def _split_long_paragraphs(self, article_text: str) -> str:
        """Post-process: split long paragraphs at sentence boundaries for readability."""
        lines = article_text.split("\n")
        result = []
        for line in lines:
            stripped = line.strip()
            # Only split plain text paragraphs (not headers, lists, etc.)
            if stripped and not stripped.startswith(("#", "-", "*", ">", "!", "[")):
                # Split at Chinese sentence-ending punctuation
                parts = re.split(r'([。！？])', stripped)
                # Reassemble: punctuation belongs to the preceding sentence
                sentences = []
                current = ""
                for part in parts:
                    current += part
                    if part in "。！？" and len(current) > 20:
                        sentences.append(current)
                        current = ""
                if current:
                    sentences.append(current)
                # If any sentence is still too long, keep it as-is (don't force break)
                if sentences:
                    for s in sentences:
                        s = s.strip()
                        if s:
                            result.append(s)
                else:
                    result.append(stripped)
            else:
                result.append(line)
        return "\n".join(result)

    def _fetch_cross_company_reactions(self, item: NewsItem) -> list[dict]:
        """Search for public reactions from competitors/peers to a news item.

        Identifies the company behind the news, then searches for responses
        from key rivals and industry figures.
        """
        from src.verifier import NewsVerifier

        # Company mapping: name -> search keywords for reactions
        company_keywords = {
            "openai": ["anthropic", "google", "deepmind", "xai", "elon musk", "sama"],
            "anthropic": ["openai", "sam altman", "google", "deepmind"],
            "google": ["openai", "anthropic", "microsoft", "xai"],
            "deepseek": ["openai", "anthropic", "meta", "llama"],
            "xai": ["openai", "sam altman", "google", "anthropic"],
            "meta": ["openai", "google", "anthropic", "deepseek"],
            "replit": ["github", "copilot", "cursor", "vscode"],
        }

        # Identify company from item
        title_lower = item.title.lower()
        content_lower = item.content.lower()
        source_lower = item.source.lower() if item.source else ""

        identified_company = None
        for company in company_keywords:
            if company in title_lower or company in content_lower or company in source_lower:
                identified_company = company
                break

        if not identified_company:
            return []

        rivals = company_keywords.get(identified_company, [])
        if not rivals:
            return []

        reactions = []
        for rival in rivals:
            try:
                query = f"{rival} response reaction {item.title[:50]}"
                search_results = NewsVerifier._web_search(query, max_results=3)
                for result in search_results:
                    text = result.get("content", "") or result.get("snippet", "")
                    if text and len(text) > 30:
                        reactions.append({
                            "company": rival,
                            "source": result.get("url", ""),
                            "text": text[:500],
                        })
            except Exception as e:
                logger.debug(f"Cross-reaction search failed for {rival}: {e}")
                continue

        return reactions

    def _verify_image_for_section(self, image_url: str, section_text: str) -> bool:
        """用多模态模型审核图片是否适合当前段落内容。"""
        try:
            prompt = (
                "你是一个微信公众号配图审核员。请判断这张图片是否适合作为以下段落内容的配图。\n\n"
                "判断标准：\n"
                "1. 图片内容是否与段落主题相关\n"
                "2. 图片是否清晰、美观，适合在公众号展示\n"
                "3. 清晰的官方产品截图、演示截图、图表、代码界面、工作流截图可以保留\n"
                "4. 拒绝无关图片、低清图片、logo、头像、占位图和没有信息量的媒体封面\n\n"
                f"段落内容：{section_text[:200]}\n\n"
                "只回复 YES 或 NO，不要其他内容。"
            )
            answer = self.llm.generate_with_images(prompt, section_text[:100], [image_url])
            return answer.strip().upper().startswith("YES")
        except Exception as e:
            logger.debug(f"Image verification failed, accepting by default: {e}")
            return True

    def _get_cover_for_item(self, item: NewsItem, today: str, index: int) -> str:
        """为单条新闻获取封面图。优先官方图片，其次AI生成。"""
        # 1. Try official image first
        if item.raw_data and item.raw_data.get("official_image"):
            try:
                return self._download_as_cover(item.raw_data["official_image"], today, index)
            except Exception as e:
                logger.warning(f"Cover from official image failed: {e}")

        # 2. Try news source / benchmark images
        for image_url in self._collect_item_media(item)["images"]:
            try:
                return self._download_as_cover(image_url, today, index)
            except Exception as e:
                logger.warning(f"Cover from news failed: {e}")

        # 3. Try AI-generated cover image
        try:
            from src.image.generator import ImageGenerator
            gen = ImageGenerator()
            cover_file = gen.generate_cover(
                article_title=item.title,
                article_summary=item.content[:200],
            )
            media_id = self.publisher.upload_thumb(str(cover_file))
            logger.info(f"AI cover generated for feature {index}, media_id={media_id}")
            return media_id
        except Exception as e:
            logger.warning(f"AI cover generation failed: {e}")

        # Fallback: default thumb
        return ""

    def _download_as_cover(self, image_url: str, today: str, index: int) -> str:
        """下载图片作为封面并上传。"""
        import requests as http_requests
        import html as html_lib

        image_url = html_lib.unescape(image_url)
        resp = http_requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            raise ValueError("Not an image")

        ext = self._extension_from_content_type(content_type, "png")
        cover_path = Path("output/cover")
        cover_path.mkdir(parents=True, exist_ok=True)
        cover_file = cover_path / f"feature_{today}_{index}.{ext}"
        cover_file.write_bytes(resp.content)

        media_id = self.publisher.upload_thumb(str(cover_file))
        logger.info(f"Cover uploaded for feature {index}, media_id={media_id}")
        return media_id

    def _generate_chinese_title(self, item: NewsItem) -> str:
        """用 LLM 生成有吸引力的中文标题。"""
        raw_title = item.title.split("\n")[0].strip()
        raw_title = re.sub(r'^(Pinned:\s*|RT\s+@\w+:\s*|RT by @\w+:\s*)', '', raw_title)

        # 已经是中文标题且足够吸引人，直接返回
        if re.search(r'[一-鿿]', raw_title) and len(raw_title) >= 5:
            return raw_title[:60]

        title_prompt = (
            "你是一个微信公众号爆款标题生成器。根据以下AI科技新闻，生成一个15-25字的中文标题。\n\n"
            "要求：\n"
            "- 标题要有冲击力、能引发好奇心，让人忍不住想点开\n"
            "- 可以用对比、悬念、数据冲击、情绪词等技巧\n"
            "- 不要用「震惊」「重磅」等低质标题党词汇\n"
            "- 好的例子：\n"
            "  「百万上下文免费开放，闭源模型慌了」\n"
            "  「AI替同事谈成186笔交易，老板还蒙在鼓里」\n"
            "  「训练成本暴降73%，开源界又出王炸」\n"
            "- 只返回标题文字，不要加引号、序号或其他符号"
        )

        # LLM 生成（最多重试 2 次）
        for attempt in range(2):
            try:
                title_answer = self.llm.generate(
                    title_prompt,
                    f"原标题：{raw_title}\n内容摘要：{item.content[:300]}",
                )
                title_answer = title_answer.strip().split("\n")[0].strip()
                # 去掉引号、序号等
                title_answer = re.sub(r'^["\'「」【】《》\d.、)\s]+|["\'「」【】《》]+$', '', title_answer)
                # 确保包含中文
                if title_answer and re.search(r'[一-鿿]', title_answer) and 5 <= len(title_answer) <= 40:
                    return title_answer
                logger.warning(f"Title attempt {attempt+1} not Chinese: {title_answer}")
            except Exception as e:
                logger.warning(f"Title generation failed (attempt {attempt+1}): {e}")

        # Fallback: 规则生成中文标题
        return self._force_chinese_title(raw_title)

    @staticmethod
    def _force_chinese_title(title: str) -> str:
        """规则生成中文标题（LLM 翻译失败时的 fallback）。"""
        # 提取英文产品/模型名
        products = re.findall(r'[A-Z][A-Za-z0-9_.\-]*[A-Za-z0-9]', title)
        product = products[0] if products else ""

        # 判断动作类型
        t = title.lower()
        if any(w in t for w in ['release', 'launch', 'announce', 'live', 'available']):
            action = "正式发布"
        elif any(w in t for w in ['update', 'upgrade', 'new']):
            action = "重磅更新"
        elif any(w in t for w in ['open-source', 'open source']):
            action = "开源发布"
        elif any(w in t for w in ['introduc', 'present']):
            action = "全新推出"
        else:
            action = "最新动态"

        if product:
            return f"{product} {action}"
        return title[:30]

    @staticmethod
    def _format_news(items: list[NewsItem]) -> str:
        parts = []
        for i, item in enumerate(items, 1):
            media_lines = []
            raw = item.raw_data or {}
            content_excerpt = item.content[:500]
            if "china-ai" in (item.tags or []) and raw.get("links"):
                content_excerpt = (
                    "二手媒体线索，仅用于发现选题和原始来源；不要引用该媒体正文。"
                    "请优先根据下面参考链接中的官方公告、论文、代码仓库或演示页核验。"
                )
            if raw.get("links"):
                media_lines.append("参考链接: " + ", ".join(raw["links"][:5]))
            if raw.get("benchmark_images"):
                media_lines.append("可用图表: " + ", ".join(raw["benchmark_images"][:5]))
            if raw.get("benchmark_tables"):
                media_lines.append("指标/榜单数据:\n" + "\n\n".join(raw["benchmark_tables"][:2]))
            if raw.get("video_urls"):
                media_lines.append("可用视频: " + ", ".join(raw["video_urls"][:3]))
            if raw.get("comments"):
                media_lines.append(
                    "热门评论（前5条，官方回复优先）:\n"
                    + Pipeline._format_comments(raw.get("comments", []), limit=5)
                )
            parts.append(
                f"【{i}】来源: {item.source} | 标题: {item.title}\n"
                f"作者: {item.author} | 时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"链接: {item.url}\n"
                f"内容: {content_excerpt}\n"
                f"标签: {', '.join(item.tags) if item.tags else '无'}\n"
                f"{chr(10).join(media_lines)}\n"
            )
        return "\n---\n".join(parts)

    @staticmethod
    def _strip_html(html: str) -> str:
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _markdown_to_html(text: str) -> str:
        """将 LLM 输出的 Markdown 风格文本转为公众号友好的 HTML。"""
        # 1. 处理 Markdown 链接 [text](url) → text：url（必须在 ** 处理之前）
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1：\2', text)

        # 2. 按行处理，先处理行内 Markdown 再组装 HTML
        lines = text.strip().split("\n")
        html_parts = []

        for line in lines:
            stripped = line.strip()

            # 跳过纯分隔线
            if re.match(r'^(\*{3,}|-{3,}|_{3,})$', stripped):
                continue

            # 表格行 — 跳过不渲染（信息卡片已废弃）
            if stripped.startswith("|") and stripped.endswith("|"):
                continue

            # 参考链接行 — 渲染为极小的灰色链接
            if stripped.startswith("参考链接") or stripped.startswith("参考："):
                label_match = re.match(r'参考链接[：:]?\s*', stripped)
                if label_match:
                    rest = stripped[label_match.end():]
                else:
                    rest = stripped[3:].lstrip('：: ')
                urls = re.findall(r'https?://\S+', rest)
                if urls:
                    url_links = " ".join(
                        f'<a href="{u}" style="color:#bbb;text-decoration:none;word-break:break-all;">{u}</a>'
                        for u in urls
                    )
                    html_parts.append(
                        f'<p style="color:#888;font-size:13px;margin:6px 0;line-height:1.6;">参考：{url_links}</p>'
                    )
                continue

            # 行内 Markdown → HTML（只对非标题行处理）
            if stripped.startswith("## "):
                content = Pipeline._inline_md_to_html(stripped[3:])
                html_parts.append(f'<section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e;font-size:18px;border-left:4px solid #e94560;padding-left:10px;margin:0;">{content}</h2></section>')
            elif stripped.startswith("# "):
                content = Pipeline._inline_md_to_html(stripped[2:])
                html_parts.append(f'<h1 style="color:#1a1a2e;font-size:22px;text-align:center;">{content}</h1>')
            elif stripped.startswith("- ") or stripped.startswith("* "):
                content = Pipeline._inline_md_to_html(stripped[2:])
                html_parts.append(f'<p style="margin-left:16px;color:#333;">• {content}</p>')
            elif stripped == "":
                html_parts.append("")
            else:
                content = Pipeline._inline_md_to_html(stripped)
                html_parts.append(f'<p style="color:#333;line-height:1.8;margin:8px 0;">{content}</p>')

        return "\n".join(html_parts)

    @staticmethod
    def _inline_md_to_html(text: str) -> str:
        """将单行内的 Markdown 格式转为 HTML，清理所有残留符号。"""
        # 成对的 **...** → <strong>
        text = re.sub(r'\*\*([^*\n]+?)\*\*', r'<strong>\1</strong>', text)
        # 成对的 *...* → <em>（但不要匹配 ** 里的）
        text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<em>\1</em>', text)
        # 清理所有残留的 ** 或 *
        text = text.replace('**', '')
        text = re.sub(r'(?<!\w)\*(?!\w)', '', text)
        # 清理残留的 ##
        text = text.replace('##', '')
        return text

    @staticmethod
    def _format_comments(comments: list[dict], limit: int = 20) -> str:
        if not comments:
            return ""

        lines = []
        for idx, comment in enumerate(comments[:limit], 1):
            author = (comment.get("author") or "匿名用户").strip()
            text = (comment.get("text") or "").strip()
            if not text:
                continue
            images = comment.get("images") or []
            meta = []
            if comment.get("likes"):
                meta.append(f"赞{comment['likes']}")
            if comment.get("replies"):
                meta.append(f"回{comment['replies']}")
            if images:
                meta.append(f"图{len(images)}")
            meta_text = f" ({'，'.join(meta)})" if meta else ""
            lines.append(f"- {idx}. {author}{meta_text}: {text[:220]}")
            if images:
                lines.append("  配图: " + ", ".join(images[:3]))
            if comment.get("url"):
                lines.append("  链接: " + comment["url"])
        return "\n".join(lines)
