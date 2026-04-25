# src/crawlers/base.py
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from loguru import logger

from src.models import NewsItem


class BaseCrawler(ABC):
    def __init__(self, config: dict):
        self.config = config
        self._max_age_hours = config.get("max_age_hours", 24)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def filter_recent(self, items: list[NewsItem]) -> list[NewsItem]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._max_age_hours)
        fresh = [i for i in items if i.published_at >= cutoff]
        if len(fresh) < len(items):
            logger.info(f"{self.name}: filtered {len(items) - len(fresh)} items older than {self._max_age_hours}h")
        return fresh

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        ...
