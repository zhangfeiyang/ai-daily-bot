# src/pipeline_cache.py
"""发布历史与图片缓存。

发布历史用关键词去重：同一条新闻在不同平台 URL 不同，
但主题关键词相同（如 "Qwen3.6-27B"、"ChatGPT Images 2.0"）。
"""

import hashlib
import json
import re
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from loguru import logger

_BEIJING_TZ = timezone(timedelta(hours=8))
_HISTORY_FILE_DAILY = Path("output/published_history_daily.json")
_HISTORY_FILE_FEATURE = Path("output/published_history_feature.json")
_IMAGE_CACHE_FILE = Path("output/image_cache.json")
_MATERIAL_CACHE_FILE = Path("output/material_cache.json")

# LLM客户端缓存（延迟初始化）
_llm_client = None


def _get_llm_client():
    """延迟初始化LLM客户端。"""
    global _llm_client
    if _llm_client is None:
        from src.llm.client import LLMClient
        # 加载配置
        config_path = Path("config/llm.yaml")
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            _llm_client = LLMClient(config)
        else:
            raise RuntimeError("LLM config not found at config/llm.yaml")
    return _llm_client


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

def load_published_history(mode: str = "daily") -> list[dict]:
    """加载已发布新闻历史。返回 [{date, keywords, title}]

    Args:
        mode: "daily" 或 "feature"，决定使用哪个历史文件
    """
    history_file = _HISTORY_FILE_DAILY if mode == "daily" else _HISTORY_FILE_FEATURE
    data = _load_json(history_file)
    if isinstance(data, list):
        # 清理超过 14 天的记录
        cutoff = (datetime.now(_BEIJING_TZ) - timedelta(days=14)).strftime("%Y-%m-%d")
        cleaned = [r for r in data if r.get("date", "") >= cutoff]
        if len(cleaned) < len(data):
            _save_json(history_file, cleaned)
        return cleaned
    return []


def save_published_history(history: list[dict], mode: str = "daily"):
    """保存发布历史。

    Args:
        mode: "daily" 或 "feature"，决定使用哪个历史文件
    """
    history_file = _HISTORY_FILE_DAILY if mode == "daily" else _HISTORY_FILE_FEATURE
    _save_json(history_file, history)


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

    # 提取更多中文关键词（2-4字的中文词组）
    chinese_words = re.findall(r'[一-鿿]{2,4}', text)
    for word in chinese_words:
        # 过滤掉常见的无意义词
        if word not in {'这是', '那个', '这个', '不是', '没有', '什么', '怎么', '如何', '为什么', '可以', '可能', '已经', '还是', '但是', '而且', '或者', '以及', '因为', '所以', '如果', '虽然', '就是', '只是', '还有', '也要', '都要', '都是', '更是', '才是', '也是', '更是', '已是', '正是', '都是', '全是', '倒是', '倒是', '总是', '老是', '还是', '或是', '或是', '或是'}:
            if len(word) >= 2:
                keywords.append(word)

    skip = {'The', 'This', 'New', 'For', 'And', 'From', 'With', 'Has', 'Its', 'Are', 'Images', 'OpenAI'}
    return [k for k in keywords if len(k) >= 2 and k not in skip]


def is_already_published(title: str, url: str, history: list[dict]) -> bool:
    """检查新闻是否已在历史记录中。基于标题关键词匹配 + LLM语义相似度。"""
    title_lower = title.lower()

    # 先用关键词快速匹配
    for record in history:
        for kw in record.get("keywords", []):
            if kw.lower() in title_lower:
                return True
        # 也检查历史标题是否高度重叠
        hist_title = record.get("title", "").lower()
        if hist_title and _title_overlap(title_lower, hist_title):
            return True

    # 如果关键词匹配没通过，使用LLM语义相似度检查（检查最近50条，覆盖更广）
    recent_records = [r for r in history[-50:] if r.get("title")]
    if recent_records:
        try:
            llm = _get_llm_client()
            for record in recent_records:
                hist_title = record.get("title", "")
                if hist_title:
                    similarity = _compute_title_similarity(llm, title, hist_title)
                    if similarity >= 0.75:  # 相似度 >= 75% 认为是重复（降低阈值减少漏判）
                        logger.debug(f"LLM similarity {similarity:.2f}: '{title[:30]}' vs '{hist_title[:30]}'")
                        return True
        except Exception as e:
            logger.debug(f"LLM similarity check failed: {e}")

    return False


def _compute_title_similarity(llm, title1: str, title2: str) -> float:
    """使用LLM计算两个标题的语义相似度（0-1）。"""
    prompt = """比较以下两个新闻标题，判断它们是否在报道同一件事。

标题1：{title1}
标题2：{title2}

请只返回一个0到100之间的整数，表示两个标题报道同一件事的概率：
- 0-20：完全不同的主题
- 21-40：相关但不是同一件事
- 41-60：可能是同一件事的不同角度
- 61-80：很可能是同一件事
- 81-100：绝对是同一件事

只返回数字，不要其他内容。"""

    try:
        result = llm.generate(prompt.format(title1=title1, title2=title2), "")
        # 提取数字
        match = re.search(r'(\d+)', result.strip())
        if match:
            score = int(match.group(1))
            return score / 100.0
    except Exception:
        pass
    return 0.0


def _title_overlap(a: str, b: str) -> bool:
    """检查两个标题是否有足够的词重叠。"""
    # 提取英文和中文关键词
    words_a = set(re.findall(r'[a-zA-Z0-9]{2,}|[一-鿿]{2,}', a))
    words_b = set(re.findall(r'[a-zA-Z0-9]{2,}|[一-鿿]{2,}', b))
    if not words_a or not words_b:
        return False
    overlap = words_a & words_b
    # 超过 60% 的词重叠就认为相同（提高阈值减少误判）
    return len(overlap) >= max(len(words_a), len(words_b)) * 0.6


def record_published(titles: list[str], date: str, history: list[dict], mode: str = "daily"):
    """记录一批已发布的新闻标题。

    Args:
        mode: "daily" 或 "feature"，决定使用哪个历史文件
    """
    for title in titles:
        keywords = _extract_keywords(title)
        if keywords:
            history.append({"date": date, "keywords": keywords, "title": title})
    save_published_history(history, mode)


# ── 图片缓存 ──

def _title_hash(title: str, namespace: str = "") -> str:
    normalized = f"{namespace.strip().lower()}::{title.strip().lower()[:100]}"
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


def get_cached_image(title: str, cache: dict, namespace: str = "") -> str | None:
    key = _title_hash(title, namespace)
    entry = cache.get(key)
    if not entry:
        return None
    local = entry.get("local_path", "")
    if local and Path(local).exists():
        return entry.get("wechat_url", "")
    return None


def cache_image(title: str, local_path: str, wechat_url: str, cache: dict, namespace: str = ""):
    key = _title_hash(title, namespace)
    today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    cache[key] = {
        "title": title[:80],
        "namespace": namespace[:80],
        "local_path": str(local_path),
        "wechat_url": wechat_url,
        "date": today,
    }
    save_image_cache(cache)


# ── 新闻材料持久缓存 ──

def _stable_cache_key(namespace: str, value: str) -> str:
    normalized = json.dumps(
        {"namespace": namespace, "value": value},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def load_material_cache() -> dict:
    """加载新闻材料持久缓存。永久保存，永不自动删除。"""
    data = _load_json(_MATERIAL_CACHE_FILE)
    if not isinstance(data, dict):
        return {}
    return data


def save_material_cache(cache: dict):
    _save_json(_MATERIAL_CACHE_FILE, cache)


def get_material_cache(cache: dict, namespace: str, value: str):
    key = _stable_cache_key(namespace, value)
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return None
    return entry.get("payload")


def set_material_cache(cache: dict, namespace: str, value: str, payload):
    """保存材料到缓存。payload 包含原文、截图路径、生图路径、加工文等。"""
    key = _stable_cache_key(namespace, value)
    
    # 如果已有缓存，尝试合并而不是覆盖（保留已有的截图或生图）
    existing = cache.get(key)
    if isinstance(existing, dict) and isinstance(existing.get("payload"), dict) and isinstance(payload, dict):
        # 深度合并 payload
        for k, v in payload.items():
            if v: # 只覆盖非空值
                existing["payload"][k] = v
        existing["cached_at"] = datetime.now(_BEIJING_TZ).isoformat()
    else:
        cache[key] = {
            "namespace": namespace,
            "cached_at": datetime.now(_BEIJING_TZ).isoformat(),
            "payload": payload,
        }
    save_material_cache(cache)


def get_all_materials(cache: dict) -> list[dict]:
    """返回所有已缓存的材料列表。"""
    return [
        {"key": k, **v}
        for k, v in cache.items()
        if isinstance(v, dict)
    ]
