# src/models.py
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsItem:
    source: str
    title: str
    url: str
    content: str
    author: str
    published_at: datetime
    tags: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
