from src.crawlers.twitter_crawler import TwitterCrawler


def test_fetch_top_comments_parses_replies_from_nitter_html():
    html = """
    <html>
      <body>
        <div class="timeline-item">
          <a class="username">@OpenAI</a>
          <div class="tweet-content">Original tweet</div>
        </div>
        <div class="timeline-item">
          <a class="username">@OpenAI</a>
          <a class="tweet-date" href="/OpenAI/status/111">2026-05-01</a>
          <div class="tweet-content">官方补充了图表说明</div>
          <img src="/pic/media/comment_chart.png" alt="chart" />
        </div>
        <div class="timeline-item">
          <a class="username">@user1</a>
          <a class="tweet-date" href="/user1/status/222">2026-05-01</a>
          <div class="tweet-content">补充了一些分析</div>
        </div>
      </body>
    </html>
    """

    comments = TwitterCrawler._parse_status_comments(
        html,
        instance="https://nitter.net",
        main_author="OpenAI",
        limit=3,
    )

    assert len(comments) == 2
    assert comments[0]["is_main_author"] is True
    assert comments[0]["text"] == "官方补充了图表说明"
    assert comments[0]["images"]
    assert "pbs.twimg.com" in comments[0]["images"][0]
    assert comments[1]["author"] == "@user1"


def test_parse_status_comments_prioritizes_official_reply_and_caps_at_20():
    replies = []
    for i in range(24):
        replies.append(
            f"""
            <div class="timeline-item">
              <a class="username">@user{i}</a>
              <a class="tweet-date" href="/user{i}/status/{200+i}">2026-05-01</a>
              <div class="tweet-content">reply {i} with {i} likes and {24 - i} replies</div>
            </div>
            """
        )

    html = f"""
    <html>
      <body>
        <div class="timeline-item">
          <a class="username">@OpenAI</a>
          <div class="tweet-content">Original tweet</div>
        </div>
        <div class="timeline-item">
          <a class="username">@OpenAI</a>
          <a class="tweet-date" href="/OpenAI/status/111">2026-05-01</a>
          <div class="tweet-content">official reply with 1 likes and 2 replies</div>
        </div>
        {''.join(replies)}
      </body>
    </html>
    """

    comments = TwitterCrawler._parse_status_comments(
        html,
        instance="https://nitter.net",
        main_author="OpenAI",
        limit=20,
    )

    assert len(comments) == 20
    assert comments[0]["is_main_author"] is True
    assert comments[0]["text"].startswith("official reply")
    assert comments[1]["likes"] >= comments[2]["likes"]
