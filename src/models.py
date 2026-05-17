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
    
    # 新增字段：用于全面缓存材料
    screenshots: list[str] = field(default_factory=list)      # 截图本地路径列表
    generated_images: list[str] = field(default_factory=list) # AI生图本地路径列表
    processed_content: str = ""                               # LLM 加工后的文案
    related_links: list[str] = field(default_factory=list)    # 发现的关联链接

    def to_dict(self) -> dict:
        """Serialize to dict with ISO datetime string for JSON cache."""
        from dataclasses import asdict
        d = asdict(self)
        if isinstance(d.get("published_at"), datetime):
            d["published_at"] = self.published_at.isoformat()
        return d
