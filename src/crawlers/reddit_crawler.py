# src/crawlers/reddit_crawler.py
import os
from datetime import datetime, timezone
import praw
from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class RedditCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        reddit = praw.Reddit(
            client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
            client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
            user_agent=os.environ.get("REDDIT_USER_AGENT", "ai-news-bot/1.0"),
        )
        subreddits = self.config.get("subreddits", ["MachineLearning"])
        sort = self.config.get("sort", "hot")
        limit = self.config.get("limit", 15)

        items = []
        for sub_name in subreddits:
            subreddit = reddit.subreddit(sub_name)
            if sort == "hot":
                submissions = subreddit.hot(limit=limit)
            elif sort == "new":
                submissions = subreddit.new(limit=limit)
            else:
                submissions = subreddit.top(time_filter=self.config.get("time_filter", "day"), limit=limit)

            for s in submissions:
                if s.stickied:
                    continue
                items.append(NewsItem(
                    source="reddit",
                    title=s.title,
                    url=f"https://reddit.com{s.permalink}",
                    content=s.selftext[:2000] if s.selftext else s.title,
                    author=s.author.name if s.author else "[deleted]",
                    published_at=datetime.fromtimestamp(s.created_utc, tz=timezone.utc),
                    tags=[s.link_flair_text] if s.link_flair_text else [],
                    raw_data={"score": s.score, "num_comments": s.num_comments, "subreddit": sub_name},
                ))
        return items
