# src/crawlers/base.py
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from loguru import logger

import requests
from src.models import NewsItem
from src.utils.crawler_cache import get as cache_get, set as cache_set, clear as cache_clear

_BEIJING_TZ = timezone(timedelta(hours=8))

# 系统代理地址（mihomo 本地端口）
PROXY = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or None
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None


def get_session() -> requests.Session:
    """返回带代理的 requests Session（单例）。"""
    session = requests.Session()
    if PROXIES:
        session.proxies.update(PROXIES)
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; ai-news-bot/1.0)"
    return session


class BaseCrawler(ABC):
    # 子类可通过覆盖 cache_ttl_seconds 控制 TTL，None=禁用缓存
    cache_ttl_seconds: int | None = 4 * 3600  # 默认 4 小时

    def __init__(self, config: dict):
        self.config = config
        self._max_age_hours = config.get("max_age_hours")

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def get_cache_key(self) -> str:
        """子类可覆盖以实现查询级别的缓存分区。"""
        return ""

    def cached_fetch(self) -> list[NewsItem]:
        """带缓存的 fetch：先读缓存，miss 时调用 _fetch() 并写入缓存。"""
        if self.cache_ttl_seconds is None:
            return self._fetch()

        key = self.get_cache_key()
        cached = cache_get(self.name, key, max_age_seconds=self.cache_ttl_seconds)
        if cached is not None:
            # 反序列化为 NewsItem
            return [NewsItem(**item) for item in cached]

        items = self._fetch()
        # 如果抓空，缓存结果没有意义，删除旧缓存下次强制重抓
        if not items:
            cache_clear(self.name, key)
        else:
            # 写入缓存（用 to_dict 序列化）
            cache_set(self.name, [item.to_dict() for item in items], key)
        return items

    def filter_recent(self, items: list[NewsItem]) -> list[NewsItem]:
        """过滤掉超过 _max_age_hours 的条目。用北京时间判断。"""
        if not self._max_age_hours:
            return items
        # 北京时间 naive 此刻
        now_beijing = datetime.now(_BEIJING_TZ).replace(tzinfo=None)
        cutoff = now_beijing - timedelta(hours=self._max_age_hours)

        def to_naive(dt) -> datetime:
            if isinstance(dt, str):
                # 尝试解析 ISO 字符串，否则用当前时间（表示未知/今天）
                try:
                    dt = datetime.fromisoformat(dt)
                except ValueError:
                    return now_beijing
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt

        fresh = [i for i in items if to_naive(i.published_at) >= cutoff]
        if len(fresh) < len(items):
            logger.info(f"{self.name}: filtered {len(items) - len(fresh)} items older than {self._max_age_hours}h")
        return fresh

    @abstractmethod
    def _fetch(self) -> list[NewsItem]:
        """子类实现实际抓取逻辑。"""
        ...

    def fetch(self) -> list[NewsItem]:
        """公开入口 — 由 cached_fetch 包装。子类无需覆盖。"""
        return self.cached_fetch()
