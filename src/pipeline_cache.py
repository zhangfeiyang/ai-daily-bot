# src/pipeline_cache.py
"""发布历史与图片缓存。

发布历史用关键词去重：同一条新闻在不同平台 URL 不同，
但主题关键词相同（如 "Qwen3.6-27B"、"ChatGPT Images 2.0"）。
"""

import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from loguru import logger

_BEIJING_TZ = timezone(timedelta(hours=8))
_HISTORY_FILE = Path("output/published_history.json")
_IMAGE_CACHE_FILE = Path("output/image_cache.json")


def _load_json(path: Path) -> dict | list:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {} if path == _IMAGE_CACHE_FILE else []


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 发布历史（关键词去重） ──

def load_published_history() -> list[dict]:
    """加载已发布新闻历史。返回 [{date, keywords, title}]"""
    data = _load_json(_HISTORY_FILE)
    if isinstance(data, list):
        # 清理超过 14 天的记录
        cutoff = (datetime.now(_BEIJING_TZ) - timedelta(days=14)).strftime("%Y-%m-%d")
        cleaned = [r for r in data if r.get("date", "") >= cutoff]
        if len(cleaned) < len(data):
            _save_json(_HISTORY_FILE, cleaned)
        return cleaned
    return []


def save_published_history(history: list[dict]):
    _save_json(_HISTORY_FILE, history)


def _extract_keywords(text: str) -> list[str]:
    """从标题中提取关键词。"""
    keywords = []

    # 提取英文术语（如 Qwen3.6-27B, GPT-5, MiMo-V2.5）
    for m in re.finditer(r'[A-Z][A-Za-z0-9_.\-]*[A-Za-z0-9]', text):
        term = m.group()
        if len(term) >= 3:
            keywords.append(term)
        # 也提取独立的部分（如 LLaDA2.0-Uni → LLaDA）
        parts = re.split(r'[\-._]', term)
        for p in parts:
            p = re.sub(r'^\d+$', '', p)  # 去掉纯数字
            if len(p) >= 3:
                keywords.append(p)

    # 提取中文术语
    for m in re.finditer(r'[一-鿿]{2,6}(?:模型|发布|推出|升级|开源)', text):
        keywords.append(m.group())

    skip = {'The', 'This', 'New', 'For', 'And', 'From', 'With', 'Has', 'Its', 'Are', 'Images', 'OpenAI'}
    return [k for k in keywords if len(k) >= 3 and k not in skip]


def is_already_published(title: str, url: str, history: list[dict]) -> bool:
    """检查新闻是否已在历史记录中。基于标题关键词匹配。"""
    title_lower = title.lower()
    for record in history:
        for kw in record.get("keywords", []):
            if kw.lower() in title_lower:
                return True
        # 也检查历史标题是否高度重叠
        hist_title = record.get("title", "").lower()
        if hist_title and _title_overlap(title_lower, hist_title):
            return True
    return False


def _title_overlap(a: str, b: str) -> bool:
    """检查两个标题是否有足够的词重叠。"""
    # 提取英文和中文关键词
    words_a = set(re.findall(r'[a-zA-Z0-9]{2,}|[一-鿿]{2,}', a))
    words_b = set(re.findall(r'[a-zA-Z0-9]{2,}|[一-鿿]{2,}', b))
    if not words_a or not words_b:
        return False
    overlap = words_a & words_b
    # 超过 50% 的词重叠就认为相同
    return len(overlap) >= max(len(words_a), len(words_b)) * 0.5


def record_published(titles: list[str], date: str, history: list[dict]):
    """记录一批已发布的新闻标题。"""
    for title in titles:
        keywords = _extract_keywords(title)
        if keywords:
            history.append({"date": date, "keywords": keywords, "title": title})
    save_published_history(history)


# ── 图片缓存 ──

def _title_hash(title: str) -> str:
    normalized = title.strip().lower()[:100]
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def load_image_cache() -> dict:
    data = _load_json(_IMAGE_CACHE_FILE)
    if isinstance(data, dict):
        cutoff = (datetime.now(_BEIJING_TZ) - timedelta(days=14)).strftime("%Y-%m-%d")
        cleaned = {k: v for k, v in data.items() if v.get("date", "") >= cutoff}
        if len(cleaned) < len(data):
            _save_json(_IMAGE_CACHE_FILE, cleaned)
        return cleaned
    return {}


def save_image_cache(cache: dict):
    _save_json(_IMAGE_CACHE_FILE, cache)


def get_cached_image(title: str, cache: dict) -> str | None:
    key = _title_hash(title)
    entry = cache.get(key)
    if not entry:
        return None
    local = entry.get("local_path", "")
    if local and Path(local).exists():
        return entry.get("wechat_url", "")
    return None


def cache_image(title: str, local_path: str, wechat_url: str, cache: dict):
    key = _title_hash(title)
    today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    cache[key] = {
        "title": title[:80],
        "local_path": str(local_path),
        "wechat_url": wechat_url,
        "date": today,
    }
    save_image_cache(cache)
