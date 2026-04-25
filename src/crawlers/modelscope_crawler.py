# src/crawlers/modelscope_crawler.py
from datetime import datetime, timezone
import re

import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class ModelScopeCrawler(BaseCrawler):
    """爬取 ModelScope 热门模型。通过 HuggingFace API 搜索 modelscope 相关模型。"""

    def fetch(self) -> list[NewsItem]:
        max_results = self.config.get("max_results", 15)

        items = []
        try:
            # 通过 HuggingFace API 搜索带有 modelscope 标签或 Qwen 等国产模型的近期模型
            cutoff = (datetime.now(timezone.utc) - __import__('datetime').timedelta(hours=72)).strftime("%Y-%m-%d")
            api_url = "https://huggingface.co/api/models"
            params = {
                "search": "modelscope",
                "limit": max_results,
            }
            resp = requests.get(
                api_url,
                params=params,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
            )
            resp.raise_for_status()
            models = resp.json()

            for model in models[:max_results]:
                item = self._parse_model(model)
                if item:
                    items.append(item)

        except Exception as e:
            logger.warning(f"ModelScope: failed to fetch: {e}")

        return self.filter_recent(items)

    def _parse_model(self, model: dict) -> NewsItem | None:
        model_id = model.get("modelId", model.get("id", ""))
        if not model_id:
            return None

        author = model.get("author", model_id.split("/")[0] if "/" in model_id else "")
        name = model_id.split("/")[-1] if "/" in model_id else model_id

        description = model.get("description", "") or ""
        tags = model.get("tags", []) or []
        pipeline_tag = model.get("pipeline_tag", "")
        if pipeline_tag:
            tags.insert(0, pipeline_tag)

        title = f"[ModelScope] {name}"
        content = description[:2000] if description else f"模型 {model_id}"

        return NewsItem(
            source="modelscope",
            title=title,
            url=f"https://huggingface.co/{model_id}",
            content=content,
            author=author or "ModelScope",
            published_at=datetime.now(timezone.utc),
            tags=[t for t in tags if isinstance(t, str)][:5],
            raw_data={"model_id": model_id, "image_url": ""},
        )
