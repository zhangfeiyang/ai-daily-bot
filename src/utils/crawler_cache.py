"""Crawler result cache — avoids redundant HTTP requests across runs."""

import hashlib
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from loguru import logger

_CACHE_DIR = Path.home() / ".cache" / "gongzhonghao"
_DEFAULT_TTL_SECONDS = 4 * 3600  # 4 hours


def _ensure_cache_dir():
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(crawler_name: str, query_key: str = "") -> Path:
    """Return the JSON file path for a given crawler + query combination."""
    key = hashlib.md5(query_key.encode()).hexdigest()[:12]
    return _CACHE_DIR / f"{crawler_name}_{key}.json"


def get(crawler_name: str, query_key: str = "", max_age_seconds: int = _DEFAULT_TTL_SECONDS) -> list | None:
    """
    Return cached items if they exist and are fresh, else None.
    
    Args:
        crawler_name: unique name of the crawler (e.g. "huggingface", "arxiv")
        query_key: additional qualifier (e.g. search query, subreddit name)
        max_age_seconds: cache TTL; items older than this are considered stale
    
    Returns:
        List of cached NewsItem dicts, or None if cache miss / stale / error.
    """
    _ensure_cache_dir()
    path = _cache_path(crawler_name, query_key)
    if not path.exists():
        return None

    try:
        with open(path) as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"CrawlerCache: failed to read {path}: {e}")
        return None

    cached_at = entry.get("cached_at", 0)
    age = time.time() - cached_at
    if age > max_age_seconds:
        logger.debug(f"CrawlerCache: {crawler_name} stale ({age:.0f}s old > {max_age_seconds}s), refetching")
        return None

    items = entry.get("items", [])
    logger.info(f"CrawlerCache: {crawler_name} hit ({len(items)} items, {age:.0f}s old)")
    return items


def set(crawler_name: str, items: list, query_key: str = ""):
    """
    Persist a list of NewsItem dicts to the cache.
    
    Args:
        crawler_name: unique name of the crawler
        items: list of NewsItem dictionaries (as serialised by NewsItem.to_dict())
        query_key: additional qualifier used in get()
    """
    _ensure_cache_dir()
    path = _cache_path(crawler_name, query_key)
    entry = {
        "cached_at": time.time(),
        "crawler": crawler_name,
        "query_key": query_key,
        "count": len(items),
        "items": items,
    }
    try:
        with open(path, "w") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        logger.debug(f"CrawlerCache: saved {crawler_name} {len(items)} items to {path.name}")
    except OSError as e:
        logger.warning(f"CrawlerCache: failed to write {path}: {e}")


def clear(crawler_name: str = None, query_key: str = ""):
    """
    Clear cache for a specific crawler, or all caches if crawler_name is None.
    """
    _ensure_cache_dir()
    if crawler_name is None:
        for p in _CACHE_DIR.glob("*.json"):
            p.unlink()
        logger.info("CrawlerCache: cleared all")
        return
    path = _cache_path(crawler_name, query_key)
    if path.exists():
        path.unlink()
        logger.info(f"CrawlerCache: cleared {crawler_name}")
