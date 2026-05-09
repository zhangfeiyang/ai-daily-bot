# main.py
import sys
import time
from pathlib import Path
import re
from datetime import datetime, timedelta, timezone
from loguru import logger
from src.config import load_config
from src.crawlers.arxiv_crawler import ArxivCrawler
from src.crawlers.reddit_crawler import RedditCrawler
from src.crawlers.twitter_crawler import TwitterCrawler
from src.crawlers.huggingface_crawler import HuggingFaceCrawler
from src.crawlers.modelscope_crawler import ModelScopeCrawler
from src.crawlers.github_crawler import GitHubCrawler
from src.crawlers.china_ai_crawler import ChinaAICrawler
from src.llm.client import LLMClient
from src.pipeline import Pipeline
from src.publish.wechat import WeChatPublisher
from src.verifier import NewsVerifier


def _retry_call(func, *args, max_retries: int = 3, delay: float = 5.0, **kwargs):
    """Retry a function call with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait:.1f}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {max_retries} attempts failed: {e}")
    raise last_error


def setup_logging():
    log_dir = "logs"
    logger.add(
        f"{log_dir}/{{time:YYYY-MM-DD}}.log",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level="INFO",
    )


def build_crawlers(sources_config: dict) -> list:
    crawlers = []
    if sources_config.get("arxiv", {}).get("enabled", False):
        crawlers.append(ArxivCrawler(sources_config["arxiv"]))
    if sources_config.get("reddit", {}).get("enabled", False):
        crawlers.append(RedditCrawler(sources_config["reddit"]))
    if sources_config.get("twitter", {}).get("enabled", False):
        crawlers.append(TwitterCrawler(sources_config["twitter"]))
    if sources_config.get("huggingface", {}).get("enabled", False):
        crawlers.append(HuggingFaceCrawler(sources_config["huggingface"]))
    if sources_config.get("modelscope", {}).get("enabled", False):
        crawlers.append(ModelScopeCrawler(sources_config["modelscope"]))
    if sources_config.get("github", {}).get("enabled", False):
        crawlers.append(GitHubCrawler(sources_config["github"]))
    if sources_config.get("china_ai", {}).get("enabled", False):
        crawlers.append(ChinaAICrawler(sources_config["china_ai"]))
    return crawlers


def build_live_crawlers(sources_config: dict) -> list:
    """Build a conservative source set for real daily runs.

    Default to the most stable source. Extra sources can be enabled with env vars:
    - DAILY_LIVE_INCLUDE_ARXIV=1
    """
    import os

    crawlers = []
    if sources_config.get("github", {}).get("enabled", False):
        crawlers.append(GitHubCrawler(sources_config["github"]))
    if os.environ.get("DAILY_LIVE_INCLUDE_ARXIV") == "1" and sources_config.get("arxiv", {}).get("enabled", False):
        crawlers.append(ArxivCrawler(sources_config["arxiv"]))
    return crawlers


def _extract_article_title_from_html(html: str, fallback: str = "") -> str:
    match = re.search(r"<!--\s*ARTICLE_TITLE:\s*(.*?)\s*-->", html, flags=re.S)
    if match:
        return match.group(1).strip()
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.S | re.I)
    if match:
        title = re.sub(r"<[^>]+>", "", match.group(1))
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            return title
    return fallback


def _extract_thumb_media_id_from_html(html: str) -> str:
    match = re.search(r"<!--\s*THUMB_MEDIA_ID:\s*(.*?)\s*-->", html, flags=re.S)
    if match:
        return match.group(1).strip()
    return ""


def _upload_daily_draft(publisher: WeChatPublisher) -> bool:
    """Upload today's staged daily article to the WeChat draft box."""
    beijing_tz = timezone(timedelta(hours=8))
    today = datetime.now(beijing_tz).strftime("%Y-%m-%d")
    article_file = Path(f"output/articles/daily_{today}.html")
    if not article_file.exists():
        logger.error(f"No staged daily article found for {today}")
        return False

    try:
        html = article_file.read_text(encoding="utf-8")
        title = _extract_article_title_from_html(html, fallback=article_file.stem)
        thumb_media_id = _extract_thumb_media_id_from_html(html)
        media_id = _retry_call(
            publisher.create_draft,
            title=title,
            content=html,
            thumb_media_id=thumb_media_id,
            max_retries=3,
            delay=5.0,
        )
        logger.info(f"Daily draft uploaded from {article_file} -> {media_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload daily draft {article_file}: {e}")
        return False


def _upload_feature_drafts(publisher: WeChatPublisher) -> bool:
    """Upload today's staged feature articles to the WeChat draft box."""
    beijing_tz = timezone(timedelta(hours=8))
    today = datetime.now(beijing_tz).strftime("%Y-%m-%d")
    article_files = sorted(Path("output/articles").glob(f"feature_{today}_*.html"))
    if not article_files:
        logger.error(f"No staged feature articles found for {today}")
        return False

    ok = False
    for article_file in article_files:
        try:
            html = article_file.read_text(encoding="utf-8")
            title = _extract_article_title_from_html(html, fallback=article_file.stem)
            thumb_media_id = _extract_thumb_media_id_from_html(html)
            media_id = _retry_call(
                publisher.create_draft,
                title=title,
                content=html,
                thumb_media_id=thumb_media_id,
                max_retries=3,
                delay=5.0,
            )
            logger.info(f"Feature draft uploaded from {article_file} -> {media_id}")
            ok = True
        except Exception as e:
            logger.error(f"Failed to upload feature draft {article_file}: {e}")
            return False

    return ok


def mark_published():
    """将指定日期的文章标记为已发布，提取 h2 标题做关键词去重。"""
    import re
    from pathlib import Path
    from src.pipeline_cache import load_published_history, record_published

    date = sys.argv[2] if len(sys.argv) > 2 else None
    if not date:
        from pathlib import Path
        articles = sorted(Path("output/articles").glob("daily_*.html"), reverse=True)
        if articles:
            print("可标记的文章:")
            for f in articles[:5]:
                print(f"  {f.stem.replace('daily_', '')}")
            print(f"\nUsage: python main.py mark-published <date>")
        else:
            print("没有可标记的文章")
        return

    article_file = Path(f"output/articles/daily_{date}.html")
    if not article_file.exists():
        print(f"找不到 {date} 的文章")
        sys.exit(1)

    html = article_file.read_text(encoding="utf-8")
    titles = re.findall(r'<h2 style="color:#1a1a2e[^"]*">([^<]+)</h2>', html)

    if not titles:
        print(f"文章中没有找到新闻标题")
        sys.exit(1)

    history = load_published_history()
    record_published(titles, date, history)

    print(f"已标记 {date} 的 {len(titles)} 条新闻为已发布:")
    for t in titles:
        print(f"  - {t}")
    print(f"发布历史总计: {len(load_published_history())} 条")


def main():
    valid_modes = ("daily", "daily-live", "weekly", "test", "mark-published", "feature", "draft", "video")
    if len(sys.argv) < 2 or sys.argv[1] not in valid_modes:
        print("Usage: python main.py <daily|daily-live|weekly|test|feature|draft|video|mark-published [date]>")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "mark-published":
        mark_published()
        return

    setup_logging()
    logger.info(f"Starting pipeline in '{mode}' mode")

    if mode == "video":
        if len(sys.argv) < 3:
            print("Usage: python main.py video <article.html> [more.html...]")
            sys.exit(1)

        from src.video.pipeline import VideoPipeline
        pipeline = VideoPipeline.from_config()
        ok = False
        for article_file in [Path(arg) for arg in sys.argv[2:]]:
            if not article_file.exists():
                logger.error(f"Video source not found: {article_file}")
                continue
            result = pipeline.generate(article_file)
            if result and result.exists():
                logger.info(f"Video generated from {article_file}: {result}")
                ok = True
            else:
                logger.error(f"Video generation failed for {article_file}")

        if not ok:
            sys.exit(1)
        return

    if mode == "draft":
        if len(sys.argv) < 3:
            print("Usage: python main.py draft <article.html> [more.html...]")
            sys.exit(1)

        wechat_config = load_config("wechat")
        publisher = WeChatPublisher(wechat_config)
        article_files = [Path(arg) for arg in sys.argv[2:]]
        ok = False
        for article_file in article_files:
            if not article_file.exists():
                logger.error(f"Draft source not found: {article_file}")
                continue
            html = article_file.read_text(encoding="utf-8")
            title = _extract_article_title_from_html(html, fallback=article_file.stem)
            thumb_media_id = _extract_thumb_media_id_from_html(html)
            media_id = publisher.create_draft(
                title=title,
                content=html,
                thumb_media_id=thumb_media_id,
            )
            logger.info(f"Draft uploaded from {article_file} -> {media_id}")
            ok = True

        if not ok:
            sys.exit(1)
        return

    # Load config
    sources_config = load_config("sources")
    llm_config = load_config("llm")
    wechat_config = load_config("wechat")

    # Build components
    if mode == "daily-live":
        crawlers = build_live_crawlers(sources_config)
    else:
        crawlers = build_crawlers(sources_config)
    llm_client = LLMClient(llm_config)

    if mode == "test":
        # Test mode: crawl only, no publish
        logger.info("Test mode: crawling only")
        for crawler in crawlers:
            try:
                items = crawler.fetch()
                logger.info(f"{crawler.name}: {len(items)} items")
                for item in items[:3]:
                    logger.info(f"  - {item.title}")
            except Exception as e:
                logger.error(f"{crawler.name} failed: {e}")
        return

    debug = "--debug" in sys.argv

    publisher = WeChatPublisher(wechat_config)

    # Build verifier for feature mode
    verifier = None
    if mode == "feature":
        official_config = load_config("official_sources")
        verifier = NewsVerifier(llm_client, official_config)

    # Run pipeline
    pipeline = Pipeline(
        mode="daily" if mode == "daily-live" else mode,
        crawlers=crawlers,
        llm_client=llm_client,
        publisher=publisher,
        verifier=verifier,
        debug=debug,
    )

    if mode == "feature":
        success = pipeline.run_feature()
    else:
        success = pipeline.run()

    if success:
        logger.info("Pipeline completed successfully")
        # Force refresh access_token before upload to avoid expiration after long runs
        publisher._token = None
        publisher._token_expires = 0
        if mode == "feature":
            if not _upload_feature_drafts(publisher):
                logger.error("Feature draft upload failed")
                sys.exit(1)
        elif mode in ("daily", "daily-live"):
            if not _upload_daily_draft(publisher):
                logger.error("Daily draft upload failed")
                sys.exit(1)
    else:
        logger.error("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
