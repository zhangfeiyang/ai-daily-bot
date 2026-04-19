# src/pipeline.py
from datetime import datetime, timezone
from pathlib import Path
import re
from loguru import logger
from src.llm.client import LLMClient
from src.llm.prompts import load_prompt
from src.models import NewsItem
from src.publish.wechat import WeChatPublisher as WechatPublisher
from src.tts.engine import TTSEngine


class Pipeline:
    def __init__(
        self,
        mode: str,
        crawlers: list,
        llm_client: LLMClient,
        tts_engine: TTSEngine,
        publisher: WechatPublisher,
    ):
        self.mode = mode
        self.crawlers = crawlers
        self.llm = llm_client
        self.tts = tts_engine
        self.publisher = publisher

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

            # 2. Deduplicate
            all_items = self._deduplicate(all_items)
            logger.info(f"After dedup: {len(all_items)} items")

            # 3. LLM generate article
            logger.info("Generating article via LLM...")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            news_text = self._format_news(all_items)
            template_name = "daily" if self.mode == "daily" else "weekly"

            system_prompt = load_prompt(template_name, date=today, news_content=news_text)
            article_html = self.llm.generate(system_prompt, news_text)

            # Save article
            output_dir = Path("output/articles")
            output_dir.mkdir(parents=True, exist_ok=True)
            article_path = output_dir / f"{self.mode}_{today}.html"
            article_path.write_text(article_html, encoding="utf-8")
            logger.info(f"Article saved to {article_path}")

            # 4. TTS generate audio
            logger.info("Generating audio via TTS...")
            clean_text = self._strip_html(article_html)
            audio_dir = Path("output/audio")
            audio_dir.mkdir(parents=True, exist_ok=True)
            audio_path = str(audio_dir / f"{self.mode}_{today}.mp3")
            self.tts.generate(clean_text, audio_path)

            # 5. Publish
            logger.info("Publishing to WeChat...")
            audio_media_id = self.publisher.upload_audio(audio_path)
            title = f"AI 科技前沿 | {today}"
            publish_id = self.publisher.publish_article(
                title=title,
                content=article_html,
                audio_media_id=audio_media_id,
            )
            logger.info(f"Published successfully, publish_id={publish_id}")
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
