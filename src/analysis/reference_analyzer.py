# src/analysis/reference_analyzer.py
"""分析文章中的参考链接和 Twitter 提及。"""

import re
import json
from urllib.parse import urlparse
from collections import Counter
from datetime import datetime

from bs4 import BeautifulSoup


# 域名分类映射
DOMAIN_CATEGORIES = {
    "papers": ["arxiv.org", "openreview.net", "paperswithcode.com", "neurips.cc", "icml.cc", "iclr.cc", "cvfoundation.org", "thecvf.com", "aaai.org", "aclweb.org", "aclanthology.org"],
    "code": ["github.com", "huggingface.co", "gitlab.com", "gitee.com"],
    "social": ["twitter.com", "x.com", "weibo.com", "zhihu.com", "mp.weixin.qq.com", "toutiao.com"],
    "official": ["openai.com", "anthropic.com", "google.com", "googleblog.com", "microsoft.com", "apple.com", "amazon.com", "meta.com", "nvidia.com", "intel.com", "amd.com", "qualcomm.com"],
    "tech_media": ["techcrunch.com", "theverge.com", "wired.com", "arstechnica.com", "venturebeat.com", "mittechreview.com", "nature.com", "science.org"],
    "video": ["youtube.com", "youtu.be", "bilibili.com"],
}

# 参考链接提取的正则模式
REFERENCE_PATTERNS = [
    r'(?:来源|参考|原文|参考链接|出處|转载自)[：:]\s*(https?://[^\s<>"{}|\\^`\[\]]+)',
    r'(?:Paper|论文地址|论文链接|项目链接|代码地址|GitHub|项目主页)[：:]\s*(https?://[^\s<>"{}|\\^`\[\]]+)',
    r'(?:arXiv|arxiv)[：:]\s*(https?://[^\s<>"{}|\\^`\[\]]+)',
]

# Twitter/X 提及提取模式
TWITTER_PATTERNS = [
    r'(?:twitter\.com|x\.com)/(\w{1,15})',
    r'(?:@)([a-zA-Z_]\w{0,14})',
    r'(?:在|于)\s*[Xx]\s*上(?:发帖|发表|宣布|分享|表示)',
    r'([\w一-鿿]+)\s*在\s*[XxTwitter]+\s*上',
]

# 常见 AI 人物 Twitter 账号（用于匹配文本提及）
KNOWN_TWITTER_ACCOUNTS = {
    "sama": "Sam Altman",
    "elonmusk": "Elon Musk",
    "ylecun": "Yann LeCun",
    "karpathy": "Andrej Karpathy",
    "goodfellow_ian": "Ian Goodfellow",
    "hardmaru": "David Ha",
    "jeremyphoward": "Jeremy Howard",
    "emilymbender": "Emily Bender",
    "timnitgebru": "Timnit Gebru",
    "drfeifei": "Fei-Fei Li",
    "andrewyng": "Andrew Ng",
    "demishassabis": "Demis Hassabis",
    "satyanadella": "Satya Nadella",
    "sundarpichai": "Sundar Pichai",
    "tim_cook": "Tim Cook",
    "satya": "Satya Nadella",
    "jack": "Jack Dorsey",
    "pichai": "Sundar Pichai",
    "jeffdean": "Jeff Dean",
    "schmidhuber": "Jürgen Schmidhuber",
    "hinton": "Geoffrey Hinton",
    "bengio": "Yoshua Bengio",
    "ilyasut": "Ilya Sutskever",
    "gregbrockman": "Greg Brockman",
    "miramurati": "Mira Murati",
    "alexandr_wang": "Alexandr Wang",
    "emadmostaque": "Emad Mostaque",
    "stabilityai": "Stability AI",
    "huggingface": "Hugging Face",
    "deepmind": "DeepMind",
    "openai": "OpenAI",
    "anthropicai": "Anthropic",
    "googleai": "Google AI",
    "microsoftai": "Microsoft AI",
    "metaai": "Meta AI",
    "nvidiaai": "NVIDIA AI",
    "baidu": "Baidu",
    "alibaba": "Alibaba",
    "tencent": "Tencent",
    "bytedance": "ByteDance",
}


def is_internal_url(url: str) -> bool:
    """判断 URL 是否为内部资源（图片、CDN、自身站点等）。"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
    except Exception:
        return True

    # 图片/静态资源域名
    internal_prefixes = ["image.", "cdn.", "img.", "static.", "assets.", "upload."]
    if any(domain.startswith(p) for p in internal_prefixes):
        return True

    # 自身站点域名
    own_domains = [
        "aiera.com.cn", "qbitai.com", "jiqizhixin.com",
        "zhidx.com", "leiphone.com",
    ]
    if any(d in domain for d in own_domains):
        return True

    # 图片文件后缀
    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico"]
    if any(path.endswith(ext) for ext in image_extensions):
        return True

    # 分享链接
    if "service.weibo.com" in domain:
        return True

    return False


def filter_reference_urls(urls: list[str]) -> list[str]:
    """过滤掉内部URL，只保留外部参考链接。"""
    return [url for url in urls if not is_internal_url(url)]


def extract_urls_from_html(html_content: str) -> list[str]:
    """从 HTML 内容中提取所有 URL。"""
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    urls = []

    # 提取所有 a 标签的 href
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            urls.append(href)

    # 也从纯文本中提取（markdown格式的链接）
    text = soup.get_text()
    text_urls = extract_urls_from_text(text)
    urls.extend(text_urls)

    # 去重
    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls


def extract_urls_from_text(text: str) -> list[str]:
    """从纯文本中提取 URL。"""
    if not text:
        return []

    # 匹配 http/https URL
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)

    # 去重
    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls


def extract_reference_urls(text: str) -> list[str]:
    """提取明确标记为参考/来源的 URL。"""
    urls = []
    for pattern in REFERENCE_PATTERNS:
        matches = re.findall(pattern, text)
        urls.extend(matches)
    return urls


def extract_twitter_mentions(text: str) -> dict:
    """提取 Twitter/X 提及。"""
    mentions = {
        "direct_links": [],
        "at_mentions": [],
        "text_references": [],
        "all_accounts": [],
    }

    if not text:
        return mentions

    # 直接 Twitter/X 链接
    direct_pattern = r'(?:twitter\.com|x\.com)/(\w{1,15})'
    direct_matches = re.findall(direct_pattern, text)
    mentions["direct_links"] = direct_matches
    mentions["all_accounts"].extend(direct_matches)

    # @提及
    at_pattern = r'(?:^|\s)@(\w{1,15})(?:\s|$|[,;:.])'
    at_matches = re.findall(at_pattern, text)
    mentions["at_mentions"] = at_matches
    mentions["all_accounts"].extend(at_matches)

    # 文本中的 "在X上" 引用
    x_ref_pattern = r'([\w一-鿿]{2,20})\s*在\s*[Xx]\s*上(?:发帖|发表|宣布|分享|表示|评论)'
    x_refs = re.findall(x_ref_pattern, text)
    mentions["text_references"] = x_refs

    # 去重
    mentions["all_accounts"] = list(set(mentions["all_accounts"]))

    return mentions


def categorize_domain(domain: str) -> str:
    """根据域名分类。"""
    domain_lower = domain.lower()

    for category, domains in DOMAIN_CATEGORIES.items():
        if any(d in domain_lower for d in domains):
            return category

    # 内部资源域名（排除）
    internal_domains = [
        "image.", "cdn.", "img.", "static.", "assets.",
        "aiera.com.cn", "qbitai.com", "jiqizhixin.com",
        "service.weibo.com",  # 分享链接不算参考
    ]
    if any(d in domain_lower for d in internal_domains):
        return "internal"

    return "other"


def analyze_urls(urls: list[str]) -> dict:
    """分析 URL 列表，返回统计信息。"""
    if not urls:
        return {
            "total": 0,
            "unique_domains": 0,
            "top_domains": [],
            "by_category": {},
        }

    # 提取域名
    domains = []
    for url in urls:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            # 移除 www. 前缀
            if domain.startswith("www."):
                domain = domain[4:]
            domains.append(domain)
        except Exception:
            continue

    # 域名统计
    domain_counts = Counter(domains)
    top_domains = [
        {"domain": d, "count": c}
        for d, c in domain_counts.most_common(20)
    ]

    # 分类统计
    category_counts = Counter()
    for domain in domains:
        category = categorize_domain(domain)
        category_counts[category] += 1

    return {
        "total": len(urls),
        "unique_domains": len(domain_counts),
        "top_domains": top_domains,
        "by_category": dict(category_counts),
    }


def analyze_article(item: dict) -> dict:
    """分析单篇文章的参考链接和 Twitter 提及。"""
    # 获取内容
    full_content = item.get("raw_data", {}).get("full_content", "")
    text_content = item.get("content", "")

    # 提取所有 URL
    html_urls = extract_urls_from_html(full_content)
    text_urls = extract_urls_from_text(text_content)
    all_urls = list(set(html_urls + text_urls))

    # 过滤掉内部URL（图片、CDN、自身站点等）
    reference_urls = filter_reference_urls(all_urls)

    # 提取参考链接（明确标记的）
    ref_urls = extract_reference_urls(text_content)

    # 提取 Twitter 提及
    twitter_mentions = extract_twitter_mentions(text_content)

    # 也检查 full_content 中的 Twitter 提及
    if full_content:
        twitter_from_html = extract_twitter_mentions(
            BeautifulSoup(full_content, "html.parser").get_text()
        )
        # 合并
        for key in ["direct_links", "at_mentions", "text_references"]:
            twitter_mentions[key] = list(set(
                twitter_mentions[key] + twitter_from_html[key]
            ))
        twitter_mentions["all_accounts"] = list(set(
            twitter_mentions["all_accounts"] + twitter_from_html["all_accounts"]
        ))

    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "published_at": item.get("published_at", ""),
        "urls": {
            "all": reference_urls,
            "reference_marked": ref_urls,
            "count": len(reference_urls),
        },
        "twitter": twitter_mentions,
    }


def analyze_media_articles(articles: list[dict]) -> dict:
    """分析一个媒体的所有文章。"""
    all_urls = []
    all_ref_urls = []
    all_twitter_accounts = []
    article_analyses = []

    for article in articles:
        analysis = analyze_article(article)
        article_analyses.append(analysis)

        all_urls.extend(analysis["urls"]["all"])
        all_ref_urls.extend(analysis["urls"]["reference_marked"])
        all_twitter_accounts.extend(analysis["twitter"]["all_accounts"])

    # 分析所有 URL
    url_stats = analyze_urls(all_urls)
    ref_url_stats = analyze_urls(all_ref_urls)

    # Twitter 账号统计
    twitter_counter = Counter(all_twitter_accounts)
    top_twitter = [
        {"account": acc, "count": c}
        for acc, c in twitter_counter.most_common(30)
    ]

    return {
        "articles_analyzed": len(articles),
        "url_stats": url_stats,
        "reference_url_stats": ref_url_stats,
        "twitter": {
            "total_mentions": len(all_twitter_accounts),
            "unique_accounts": len(twitter_counter),
            "top_accounts": top_twitter,
        },
        "article_details": article_analyses,
    }


def generate_report(results_by_media: dict) -> dict:
    """生成完整的分析报告。"""
    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {},
        "media_analysis": results_by_media,
    }

    # 生成跨媒体汇总
    all_domains = Counter()
    all_twitter = Counter()
    total_articles = 0
    total_urls = 0

    for media, data in results_by_media.items():
        total_articles += data["articles_analyzed"]
        total_urls += data["url_stats"]["total"]

        for domain_info in data["url_stats"]["top_domains"]:
            all_domains[domain_info["domain"]] += domain_info["count"]

        for acc_info in data["twitter"]["top_accounts"]:
            all_twitter[acc_info["account"]] += acc_info["count"]

    report["summary"] = {
        "total_articles": total_articles,
        "total_urls": total_urls,
        "media_count": len(results_by_media),
        "top_domains_overall": [
            {"domain": d, "count": c}
            for d, c in all_domains.most_common(20)
        ],
        "top_twitter_overall": [
            {"account": a, "count": c}
            for a, c in all_twitter.most_common(20)
        ],
    }

    return report


def save_report(report: dict, filepath: str):
    """保存报告到 JSON 文件。"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
