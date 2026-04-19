# src/crawlers/base.py
from abc import ABC, abstractmethod
from src.models import NewsItem


class BaseCrawler(ABC):
    def __init__(self, config: dict):
        self.config = config

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        ...
