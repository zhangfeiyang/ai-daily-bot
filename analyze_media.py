#!/usr/bin/env python3
"""分析新智元、机器之心、量子位的参考链接和Twitter关注。

Usage:
    python analyze_media.py [--output OUTPUT] [--max-articles N]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.crawlers.china_ai_crawler import ChinaAICrawler
from src.analysis.reference_analyzer import analyze_media_articles, generate_report, save_report


def main():
    parser = argparse.ArgumentParser(
        description="分析国内AI媒体的参考链接和Twitter关注"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output/media_analysis.json",
        help="输出JSON文件路径",
    )
    parser.add_argument(
        "--max-articles",
        "-n",
        type=int,
        default=50,
        help="每个媒体分析的文章数量",
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=14,
        help="分析最近多少天的文章",
    )
    parser.add_argument(
        "--sources",
        "-s",
        nargs="+",
        default=["quantumbit", "aiera", "jiqizhixin"],
        choices=["quantumbit", "aiera", "jiqizhixin", "zhidx", "leiphone"],
        help="要分析的媒体源",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="显示详细日志",
    )

    args = parser.parse_args()

    # Setup logging
    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    # Create output directory
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate max_age_hours
    max_age_hours = args.days * 24

    results = {}

    # Analyze each media source
    for source in args.sources:
        logger.info(f"正在分析: {source}")

        config = {
            "sources": [source],
            "max_age_hours": max_age_hours,
            "max_results": args.max_articles,
            "per_page": args.max_articles,
            "max_articles_per_source": args.max_articles,
            "filter_companies": False,  # Don't filter, get all articles
        }

        crawler = ChinaAICrawler(config)

        try:
            items = crawler.fetch()
            logger.info(f"  获取到 {len(items)} 篇文章")

            if not items:
                logger.warning(f"  {source}: 未获取到文章")
                continue

            # Convert NewsItem to dict for analysis
            articles = []
            for item in items:
                article_dict = {
                    "title": item.title,
                    "url": item.url,
                    "content": item.content,
                    "source": item.source,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "raw_data": item.raw_data,
                }
                articles.append(article_dict)

            # Analyze articles
            analysis = analyze_media_articles(articles)
            results[source] = analysis

            # Print summary
            logger.info(f"  URL数量: {analysis['url_stats']['total']}")
            logger.info(f"  独立域名: {analysis['url_stats']['unique_domains']}")
            logger.info(f"  Twitter提及: {analysis['twitter']['total_mentions']}")

        except Exception as e:
            logger.error(f"  {source} 分析失败: {e}")
            continue

    if not results:
        logger.error("没有成功分析任何媒体")
        sys.exit(1)

    # Generate final report
    report = generate_report(results)

    # Save report
    save_report(report, args.output)
    logger.info(f"\n分析报告已保存到: {args.output}")

    # Print summary
    print("\n" + "=" * 60)
    print("分析摘要")
    print("=" * 60)
    print(f"总文章数: {report['summary']['total_articles']}")
    print(f"总URL数: {report['summary']['total_urls']}")
    print(f"媒体数量: {report['summary']['media_count']}")

    print("\nTop 10 引用域名:")
    for domain_info in report['summary']['top_domains_overall'][:10]:
        print(f"  {domain_info['domain']}: {domain_info['count']}")

    print("\nTop 10 Twitter账号:")
    for acc_info in report['summary']['top_twitter_overall'][:10]:
        print(f"  @{acc_info['account']}: {acc_info['count']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
