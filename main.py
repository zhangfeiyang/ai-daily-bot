# main.py
import sys
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
    valid_modes = ("daily", "weekly", "test", "mark-published", "feature")
    if len(sys.argv) < 2 or sys.argv[1] not in valid_modes:
        print("Usage: python main.py <daily|weekly|test|feature|mark-published [date]>")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "mark-published":
        mark_published()
        return

    setup_logging()
    logger.info(f"Starting pipeline in '{mode}' mode")

    # Load config
    sources_config = load_config("sources")
    llm_config = load_config("llm")
    wechat_config = load_config("wechat")

    # Build components
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
        mode=mode,
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
    else:
        logger.error("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
