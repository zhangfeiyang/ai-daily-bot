# src/pipeline.py
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import re
from loguru import logger

_BEIJING_TZ = timezone(timedelta(hours=8))
from src.llm.client import LLMClient
from src.llm.prompts import load_prompt
from src.models import NewsItem
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
            key = cells[0]
            val = cells[1]
        else:
            key, val = "", cells[0] if cells else ""
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
        verifier=None,
        debug: bool = False,
    ):
        self.mode = mode
        self.crawlers = crawlers
        self.llm = llm_client
        self.publisher = publisher
        self.verifier = verifier
        self.debug = debug
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

            # 3. LLM generate article
            logger.info("Generating article via LLM...")
            today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
            news_text = self._format_news(all_items)
            template_name = "daily" if self.mode == "daily" else "weekly"

            system_prompt = load_prompt(template_name, date=today, news_content=news_text)
            article_text = self.llm.generate(system_prompt, news_text)

            # Convert markdown-style text to HTML for WeChat
            article_html = self._markdown_to_html(article_text)

            # Truncate if too long for WeChat (limit ~60000 chars)
            if len(article_html) > 60000:
                article_html = article_html[:60000]
                logger.warning("Article truncated to 60000 chars for WeChat compatibility")

            # Save article
            output_dir = Path("output/articles")
            output_dir.mkdir(parents=True, exist_ok=True)
            article_path = output_dir / f"{self.mode}_{today}.html"
            article_path.write_text(article_html, encoding="utf-8")
            logger.info(f"Article saved to {article_path}")

            # 4. Generate cover image
            thumb_media_id = ""
            if not self.debug:
                logger.info("Generating cover image...")
                thumb_media_id = self._generate_cover(today, all_items, article_text)

            # 4.5 Insert images for each news section
            if not self.debug:
                article_html = self._insert_section_images(article_html, all_items, article_text)

            # 5. Publish
            title = f"AI 科技前沿 | {today}"
            if self.debug:
                logger.info(f"Article saved (debug mode, not published): {title}")
            else:
                logger.info("Publishing to WeChat...")
                publish_id = self.publisher.publish_article(
                    title=title,
                    content=article_html,
                    thumb_media_id=thumb_media_id,
                )
                logger.info(f"Published successfully, publish_id={publish_id}")

            # 6. Record published history - DISABLED (only record on manual confirmation)
            # used_titles = self._extract_article_titles(article_html)
            # record_published(used_titles, today, self._pub_history)
            # logger.info(f"Recorded {len(used_titles)} published topics to history")

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
            if item.raw_data:
                img = item.raw_data.get("image_url", "")
                if img:
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
        self, article_html: str, items: list[NewsItem], article_text: str
    ) -> str:
        """Insert images for each news section, using cache when possible."""
        h2_pattern = r'<section style="margin:20px 0 8px 0;"><h2 style="color:#1a1a2e[^"]*">([^<]+)</h2></section>'
        h2_matches = list(re.finditer(h2_pattern, article_html))

        if not h2_matches:
            logger.info("No h2 sections found for image insertion")
            return article_html

        # Build title -> image_url mapping from news items
        title_to_image = {}
        for item in items:
            if item.raw_data and item.raw_data.get("image_url"):
                title_lower = item.title.lower().strip()
                title_to_image[title_lower] = item.raw_data["image_url"]

        insertions = []
        api_gen_count = 0
        cache_hit_count = 0
        used_image_urls = set()

        for match in reversed(h2_matches):
            section_title = match.group(1).strip()
            section_title_lower = section_title.lower()

            # 1. Check image cache first
            cached_url = get_cached_image(section_title, self._img_cache)
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

            # 2. Try matching news item image
            image_url = None
            for title_key, img_url in title_to_image.items():
                if img_url in used_image_urls:
                    continue
                if (section_title_lower in title_key) or (title_key in section_title_lower):
                    image_url = img_url
                    break
                section_words = set(section_title_lower.split())
                title_words = set(title_key.split())
                if section_words & title_words:
                    image_url = img_url
                    break

            img_html = None
            if image_url:
                try:
                    img_html = self._download_and_upload_image(image_url, section_title)
                    if img_html:
                        used_image_urls.add(image_url)
                except Exception as e:
                    logger.warning(f"Failed to use news image for '{section_title}': {e}")

            # 3. Fallback: generate via API
            if not img_html:
                try:
                    img_html = self._generate_section_image(section_title, article_text[:500])
                    if img_html:
                        api_gen_count += 1
                except Exception as e:
                    logger.warning(f"Failed to generate image for '{section_title}': {e}")

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

    def _download_and_upload_image(self, image_url: str, title: str) -> str | None:
        """Download image from URL, upload to WeChat, cache it."""
        import requests as http_requests
        import html as html_lib

        image_url = html_lib.unescape(image_url)
        resp = http_requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            return None

        ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "png"
        img_dir = Path("output/images")
        img_dir.mkdir(parents=True, exist_ok=True)
        local_path = img_dir / f"{hash(image_url) % 100000}.{ext}"
        local_path.write_bytes(resp.content)

        wechat_url = self.publisher.upload_image(str(local_path))
        if wechat_url:
            cache_image(title, str(local_path), wechat_url, self._img_cache)
            return (
                f'<section style="text-align:center;margin:12px 0;">'
                f'<img src="{wechat_url}" style="max-width:100%;border-radius:8px;" />'
                f'</section>'
            )
        return None

    def _generate_section_image(self, title: str, context: str) -> str | None:
        """Generate image via API, upload to WeChat, cache it."""
        try:
            from src.image.generator import ImageGenerator
            gen = ImageGenerator()
            img_dir = Path("output/images")
            img_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[^\w]', '_', title[:30])
            img_path = gen.generate_illustration(title, context, output_path=str(img_dir / f"{safe_name}.png"))
            wechat_url = self.publisher.upload_image(str(img_path))
            if wechat_url:
                cache_image(title, str(img_path), wechat_url, self._img_cache)
                return (
                    f'<section style="text-align:center;margin:12px 0;">'
                    f'<img src="{wechat_url}" style="max-width:100%;border-radius:8px;" />'
                    f'</section>'
                )
        except Exception as e:
            logger.warning(f"Image generation failed for '{title[:40]}': {e}")
        return None

    @staticmethod
    def _extract_article_titles(article_html: str) -> list[str]:
        """从文章 HTML 中提取 h2 标题（每条新闻的标题）。"""
        return re.findall(
            r'<h2 style="color:#1a1a2e[^"]*">([^<]+)</h2>', article_html
        )

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
                    if len(verified_items) >= 5:
                        break

                    result = self.verifier.verify_official(item)
                    if result["verified"]:
                        # Attach official info to item
                        item.raw_data = item.raw_data or {}
                        if result.get("official_url"):
                            item.raw_data["official_url"] = result["official_url"]
                        if result.get("official_image"):
                            item.raw_data["official_image"] = result["official_image"]

                        fresh = self.verifier.check_freshness(result.get("publish_time", ""))
                        if fresh:
                            verified_items.append(item)
                            logger.info(f"  VERIFIED (fresh): {item.title[:50]}")
                        else:
                            unverifiable_items.append(item)
                            logger.info(f"  STALE (kept as backup): {item.title[:50]}")
                    else:
                        logger.info(f"  SKIP (unverified): {item.title[:50]}")

                # 补充：fresh 的不够 5 条时，用 stale/unknown 的补
                if len(verified_items) < 5 and unverifiable_items:
                    need = 5 - len(verified_items)
                    verified_items.extend(unverifiable_items[:need])
                    logger.info(f"  Added {min(need, len(unverifiable_items))} stale/unknown items as backup")

                if not verified_items:
                    logger.warning("No verified items, using top 5 candidates as fallback")
                    verified_items = candidates[:5]
            else:
                verified_items = candidates[:5]

            logger.info(f"Verified: {len(verified_items)} items for publishing")

            # 5. Generate & publish each
            today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
            output_dir = Path("output/articles")
            output_dir.mkdir(parents=True, exist_ok=True)

            published_count = 0
            for i, item in enumerate(verified_items[:5], 1):
                logger.info(f"Generating article {i}/{len(verified_items[:5])}: {item.title[:50]}")

                # Generate Chinese title first
                chinese_title = self._generate_chinese_title(item)
                logger.info(f"  Title: {chinese_title}")

                article_html = self._generate_single_article(item, today)

                # Truncate if too long
                if len(article_html) > 60000:
                    article_html = article_html[:60000]

                # Save article
                article_path = output_dir / f"feature_{today}_{i}.html"
                article_path.write_text(article_html, encoding="utf-8")

                # Cover image: priority official_image > news image > default
                thumb_media_id = ""
                if not self.debug:
                    thumb_media_id = self._get_cover_for_item(item, today, i)

                # Use generated Chinese title
                clean_title = chinese_title
                if len(clean_title) > 60:
                    clean_title = clean_title[:57] + "..."

                # Publish
                if self.debug:
                    logger.info(f"Article {i} saved (debug mode, not published)")
                else:
                    publish_id = self.publisher.publish_article(
                        title=clean_title,
                        content=article_html,
                        thumb_media_id=thumb_media_id,
                    )
                    logger.info(f"Article {i} published: {publish_id}")
                published_count += 1

            logger.info(f"FeaturePipeline done: {published_count}/{len(verified_items[:5])} articles published")
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
        """为单条新闻生成深度文章 HTML。"""
        feature_prompt = load_prompt(
            "feature",
            title=item.title,
            source=item.source,
            author=item.author,
            date=item.published_at.strftime("%Y-%m-%d %H:%M"),
            content=item.content[:3000],
            url=item.url,
        )
        article_text = self.llm.generate(feature_prompt, item.content[:2000])
        article_html = self._markdown_to_html(article_text)

        # Insert news image if available (priority: official > source)
        image_inserted = False
        if item.raw_data and item.raw_data.get("official_image"):
            try:
                img_html = self._download_and_upload_image(
                    item.raw_data["official_image"], item.title
                )
                if img_html:
                    h2_pos = article_html.find("</h2></section>")
                    if h2_pos > 0:
                        insert_pos = h2_pos + len("</h2></section>")
                        article_html = (
                            article_html[:insert_pos]
                            + "\n" + img_html + "\n"
                            + article_html[insert_pos:]
                        )
                    else:
                        article_html = img_html + "\n" + article_html
                    image_inserted = True
            except Exception as e:
                logger.warning(f"Failed to insert official image for '{item.title[:40]}': {e}")

        if not image_inserted and item.raw_data and item.raw_data.get("image_url"):
            try:
                img_html = self._download_and_upload_image(
                    item.raw_data["image_url"], item.title
                )
                if img_html:
                    h2_pos = article_html.find("</h2></section>")
                    if h2_pos > 0:
                        insert_pos = h2_pos + len("</h2></section>")
                        article_html = (
                            article_html[:insert_pos]
                            + "\n" + img_html + "\n"
                            + article_html[insert_pos:]
                        )
                    else:
                        article_html = img_html + "\n" + article_html
            except Exception as e:
                logger.warning(f"Failed to insert image for '{item.title[:40]}': {e}")

        return article_html

    def _get_cover_for_item(self, item: NewsItem, today: str, index: int) -> str:
        """为单条新闻获取封面图。优先官方图片。"""
        # 1. Try official image first
        if item.raw_data and item.raw_data.get("official_image"):
            try:
                return self._download_as_cover(item.raw_data["official_image"], today, index)
            except Exception as e:
                logger.warning(f"Cover from official image failed: {e}")

        # 2. Try news source image
        if item.raw_data and item.raw_data.get("image_url"):
            try:
                return self._download_as_cover(item.raw_data["image_url"], today, index)
            except Exception as e:
                logger.warning(f"Cover from news failed: {e}")

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

        ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "png"
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
            parts.append(
                f"【{i}】来源: {item.source} | 标题: {item.title}\n"
                f"作者: {item.author} | 时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"链接: {item.url}\n"
                f"内容: {item.content[:500]}\n"
                f"标签: {', '.join(item.tags) if item.tags else '无'}\n"
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
        in_table = False
        table_rows = []

        for line in lines:
            stripped = line.strip()

            # 跳过纯分隔线
            if re.match(r'^(\*{3,}|-{3,}|_{3,})$', stripped):
                continue

            # 表格行
            if stripped.startswith("|") and stripped.endswith("|"):
                # 跳过表头分隔行 |---|---|
                if re.match(r'^\|[\s\-:|]+\|$', stripped):
                    continue
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                # 跳过全是 :---: 之类占位符的行
                if all(re.match(r'^:?-+:?$', c) for c in cells):
                    continue
                if not in_table:
                    in_table = True
                    table_rows = []
                table_rows.append(cells)
                continue
            elif in_table:
                html_parts.append(_render_info_card(table_rows))
                in_table = False
                table_rows = []

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

        if in_table and table_rows:
            html_parts.append(_render_info_card(table_rows))

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
