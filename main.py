# main.py
import sys
from loguru import logger
from src.config import load_config
from src.crawlers.arxiv_crawler import ArxivCrawler
from src.crawlers.reddit_crawler import RedditCrawler
from src.crawlers.twitter_crawler import TwitterCrawler
from src.llm.client import LLMClient
from src.pipeline import Pipeline
from src.publish.wechat import WeChatPublisher
from src.tts.engine import TTSEngine


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
    return crawlers


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("daily", "weekly", "test"):
        print("Usage: python main.py <daily|weekly|test>")
        sys.exit(1)

    mode = sys.argv[1]
    setup_logging()
    logger.info(f"Starting pipeline in '{mode}' mode")

    # Load config
    sources_config = load_config("sources")
    llm_config = load_config("llm")
    tts_config = load_config("tts")
    wechat_config = load_config("wechat")

    # Build components
    crawlers = build_crawlers(sources_config)
    llm_client = LLMClient(llm_config)
    tts_engine = TTSEngine(tts_config)

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

    publisher = WeChatPublisher(wechat_config)

    # Run pipeline
    pipeline = Pipeline(
        mode=mode,
        crawlers=crawlers,
        llm_client=llm_client,
        tts_engine=tts_engine,
        publisher=publisher,
    )

    success = pipeline.run()
    if success:
        logger.info("Pipeline completed successfully")
    else:
        logger.error("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
