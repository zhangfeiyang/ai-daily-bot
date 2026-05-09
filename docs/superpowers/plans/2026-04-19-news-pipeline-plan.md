# AI 科技前沿公众号自动化系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建自动化管道，从 arXiv/Reddit/Twitter 爬取 AI 科技新闻，LLM 整理成中文文章，TTS 生成音频，全自动发布到微信公众号。

**Architecture:** Python 管道式架构，配置驱动，模块解耦。Pipeline 编排器顺序调用爬虫→LLM→TTS→发布，系统 cron 定时触发。

**Tech Stack:** Python 3.12, arxiv, praw, feedparser, openai, anthropic, edge-tts, requests, pyyaml, python-dotenv, loguru

---

## File Structure

```
gongzhonghao/
├── config/
│   ├── sources.yaml          # 爬虫源配置
│   ├── llm.yaml              # LLM provider 配置
│   ├── tts.yaml              # TTS 引擎配置
│   └── wechat.yaml           # 公众号 API 配置
├── src/
│   ├── __init__.py
│   ├── models.py             # NewsItem 数据结构
│   ├── config.py             # 配置加载器
│   ├── crawlers/
│   │   ├── __init__.py
│   │   ├── base.py           # BaseCrawler 基类
│   │   ├── arxiv_crawler.py
│   │   ├── reddit_crawler.py
│   │   └── twitter_crawler.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py         # 统一 LLM 客户端
│   │   └── prompts.py        # Prompt 模板加载
│   ├── tts/
│   │   ├── __init__.py
│   │   └── engine.py         # TTS 引擎
│   ├── publish/
│   │   ├── __init__.py
│   │   └── wechat.py         # 公众号 API
│   └── pipeline.py           # 编排器
├── prompts/
│   ├── daily.md              # 每日快讯 prompt
│   └── weekly.md             # 每周深度 prompt
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_crawlers.py
│   ├── test_llm_client.py
│   ├── test_tts.py
│   ├── test_publish.py
│   └── test_pipeline.py
├── output/
│   ├── articles/
│   └── audio/
├── logs/
├── main.py
├── requirements.txt
├── .env.example
└── docs/
```

---

### Task 1: 项目脚手架 + 依赖 + 数据模型

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `src/models.py`
- Create: `output/articles/.gitkeep`
- Create: `output/audio/.gitkeep`
- Create: `logs/.gitkeep`
- Create: `tests/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
arxiv>=2.1.0
praw>=7.7.0
feedparser>=6.0.0
openai>=1.30.0
anthropic>=0.30.0
edge-tts>=6.1.0
requests>=2.31.0
pyyaml>=6.0
python-dotenv>=1.0.0
loguru>=0.7.0
pytest>=8.0.0
```

- [ ] **Step 2: 安装依赖**

Run: `cd /home/zhangfy/gongzhonghao && pip install -r requirements.txt`
Expected: 所有包安装成功

- [ ] **Step 3: 创建 .env.example**

```env
# LLM API Keys
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
CUSTOM_API_KEY=xxx

# Reddit API
REDDIT_CLIENT_ID=xxx
REDDIT_CLIENT_SECRET=xxx
REDDIT_USER_AGENT=ai-news-bot/1.0

# WeChat MP
WECHAT_APP_ID=wxXXX
WECHAT_APP_SECRET=xxx
```

- [ ] **Step 4: 创建目录结构和占位文件**

Run:
```bash
cd /home/zhangfy/gongzhonghao
touch src/__init__.py tests/__init__.py
touch output/articles/.gitkeep output/audio/.gitkeep logs/.gitkeep
mkdir -p src/crawlers src/llm src/tts src/publish config prompts
touch src/crawlers/__init__.py src/llm/__init__.py src/tts/__init__.py src/publish/__init__.py
```

- [ ] **Step 5: 写 test_models.py 测试**

```python
# tests/test_models.py
from datetime import datetime, timezone
from src.models import NewsItem


def test_news_item_creation():
    item = NewsItem(
        source="arxiv",
        title="Test Paper",
        url="https://arxiv.org/abs/2401.00001",
        content="Abstract of the paper.",
        author="Author Name",
        published_at=datetime(2026, 4, 19, 8, 0, 0, tzinfo=timezone.utc),
        tags=["AI", "LLM"],
        raw_data={"id": "2401.00001"},
    )
    assert item.source == "arxiv"
    assert item.title == "Test Paper"
    assert "AI" in item.tags
    assert item.raw_data["id"] == "2401.00001"


def test_news_item_default_tags():
    item = NewsItem(
        source="reddit",
        title="Test",
        url="https://reddit.com/r/test/1",
        content="content",
        author="user",
        published_at=datetime.now(timezone.utc),
        tags=[],
        raw_data={},
    )
    assert item.tags == []
```

- [ ] **Step 6: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src'`

- [ ] **Step 7: 实现 src/models.py**

```python
# src/models.py
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsItem:
    source: str
    title: str
    url: str
    content: str
    author: str
    published_at: datetime
    tags: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
```

- [ ] **Step 8: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_models.py -v`
Expected: 2 passed

- [ ] **Step 9: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git init
git add requirements.txt .env.example src/ tests/ output/ logs/ config/ prompts/
git commit -m "feat: project scaffolding with NewsItem model and dependencies"
```

---

### Task 2: 配置加载器

**Files:**
- Create: `src/config.py`
- Create: `config/sources.yaml`
- Create: `config/llm.yaml`
- Create: `config/tts.yaml`
- Create: `config/wechat.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写 test_config.py 测试**

```python
# tests/test_config.py
import os
import tempfile
import yaml
from src.config import load_config


def test_load_config_reads_yaml():
    with tempfile.TemporaryDirectory() as tmpdir:
        llm_path = os.path.join(tmpdir, "llm.yaml")
        with open(llm_path, "w") as f:
            yaml.dump({"default": "openai", "providers": {"openai": {"model": "gpt-4o"}}}, f)

        config = load_config("llm", config_dir=tmpdir)
        assert config["default"] == "openai"
        assert config["providers"]["openai"]["model"] == "gpt-4o"


def test_load_config_env_substitution(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.yaml")
        with open(path, "w") as f:
            yaml.dump({"key": "${TEST_API_KEY}"}, f)

        config = load_config("test", config_dir=tmpdir)
        assert config["key"] == "sk-test-123"


def test_load_config_missing_file():
    config = load_config("nonexistent", config_dir="/tmp/empty_xyz")
    assert config == {}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_config.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/config.py**

```python
# src/config.py
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv


load_dotenv()


def _substitute_env(value):
    """递归替换 ${ENV_VAR} 为环境变量值。"""
    if isinstance(value, str):
        pattern = re.compile(r"\$\{(\w+)\}")
        return pattern.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


def load_config(name: str, config_dir: str = None) -> dict:
    """加载 config/{name}.yaml，自动替换环境变量。"""
    if config_dir is None:
        config_dir = Path(__file__).parent.parent / "config"
    else:
        config_dir = Path(config_dir)

    path = config_dir / f"{name}.yaml"
    if not path.exists():
        return {}

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    return _substitute_env(data)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: 创建配置文件**

```yaml
# config/sources.yaml
arxiv:
  enabled: true
  categories:
    - cs.AI
    - cs.CL
    - cs.CV
    - cs.LG
  max_results: 20
  sort_by: submittedDate

reddit:
  enabled: true
  subreddits:
    - MachineLearning
    - artificial
    - ChatGPT
    - LocalLLaMA
  sort: hot
  limit: 15
  time_filter: day

twitter:
  enabled: true
  nitter_instances:
    - https://nitter.net
    - https://nitter.privacydev.net
  accounts:
    - OpenAI
    - GoogleAI
    - AnthropicAI
    - GoogleDeepMind
    -ylecun
    - karpathy
  limit: 20
```

```yaml
# config/llm.yaml
default: openai

providers:
  openai:
    api_key: ${OPENAI_API_KEY}
    base_url: https://api.openai.com/v1
    model: gpt-4o
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
    base_url: https://api.anthropic.com
    model: claude-sonnet-4-6-20250514
  custom:
    api_key: ${CUSTOM_API_KEY}
    base_url: https://your-endpoint/v1
    model: your-model
```

```yaml
# config/tts.yaml
default: edge-tts

edge-tts:
  voice: zh-CN-YunxiNeural
  rate: "+0%"
  output_format: mp3
```

```yaml
# config/wechat.yaml
app_id: ${WECHAT_APP_ID}
app_secret: ${WECHAT_APP_SECRET}
```

- [ ] **Step 6: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/config.py config/ tests/test_config.py
git commit -m "feat: config loader with env variable substitution and yaml configs"
```

---

### Task 3: 爬虫基类 + arXiv 爬虫

**Files:**
- Create: `src/crawlers/base.py`
- Create: `src/crawlers/arxiv_crawler.py`
- Test: `tests/test_crawlers.py`

- [ ] **Step 1: 写 test_crawlers.py — BaseCrawler + arXiv 测试**

```python
# tests/test_crawlers.py
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.crawlers.base import BaseCrawler
from src.crawlers.arxiv_crawler import ArxivCrawler
from src.models import NewsItem


class DummyCrawler(BaseCrawler):
    def fetch(self):
        return [
            NewsItem(
                source="test",
                title="t",
                url="https://example.com",
                content="c",
                author="a",
                published_at=datetime.now(timezone.utc),
            )
        ]


def test_base_crawler_fetch_raises():
    """BaseCrawler.fetch 应该抛出 NotImplementedError。"""
    crawler = BaseCrawler({})
    try:
        crawler.fetch()
        assert False, "Should have raised NotImplementedError"
    except NotImplementedError:
        pass


def test_base_crawler_name():
    crawler = DummyCrawler({"key": "val"})
    assert crawler.name == "DummyCrawler"


def test_arxiv_crawler_parse_result():
    """测试 arXiv 结果解析逻辑。"""
    mock_result = MagicMock()
    mock_result.entry_id = "http://arxiv.org/abs/2401.00001v1"
    mock_result.title = "  A Great Paper on AI  "
    mock_result.summary = "This is the abstract."
    mock_result.authors = [MagicMock(name="Alice"), MagicMock(name="Bob")]
    mock_result.authors[0].name = "Alice"
    mock_result.authors[1].name = "Bob"
    mock_result.published = datetime(2026, 4, 19, 8, 0, 0, tzinfo=timezone.utc)
    mock_result.categories = ["cs.AI", "cs.CL"]
    mock_result.pdf_url = "https://arxiv.org/pdf/2401.00001v1"

    crawler = ArxivCrawler({
        "enabled": True,
        "categories": ["cs.AI"],
        "max_results": 5,
        "sort_by": "submittedDate",
    })

    items = crawler._parse_result(mock_result)
    assert isinstance(items, NewsItem)
    assert items.source == "arxiv"
    assert items.title == "A Great Paper on AI"
    assert items.author == "Alice, Bob"
    assert "cs.AI" in items.tags


@patch("src.crawlers.arxiv_crawler.arxiv")
def test_arxiv_crawler_fetch(mock_arxiv_mod):
    """测试 fetch 调用 arxiv Client 并返回列表。"""
    mock_client = MagicMock()
    mock_arxiv_mod.Client.return_value = mock_client

    mock_result = MagicMock()
    mock_result.entry_id = "http://arxiv.org/abs/2401.00001v1"
    mock_result.title = "Test Paper"
    mock_result.summary = "Abstract"
    mock_result.authors = [MagicMock(name="Author")]
    mock_result.authors[0].name = "Author"
    mock_result.published = datetime(2026, 4, 19, tzinfo=timezone.utc)
    mock_result.categories = ["cs.AI"]
    mock_result.pdf_url = "https://arxiv.org/pdf/2401.00001v1"
    mock_client.results.return_value = iter([mock_result])

    crawler = ArxivCrawler({
        "enabled": True,
        "categories": ["cs.AI"],
        "max_results": 5,
        "sort_by": "submittedDate",
    })

    items = crawler.fetch()
    assert len(items) == 1
    assert items[0].source == "arxiv"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_crawlers.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/crawlers/base.py**

```python
# src/crawlers/base.py
from abc import ABC, abstractmethod

from src.models import NewsItem


class BaseCrawler(ABC):
    def __init__(self, config: dict):
        self.config = config

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        ...
```

- [ ] **Step 4: 实现 src/crawlers/arxiv_crawler.py**

```python
# src/crawlers/arxiv_crawler.py
import arxiv

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class ArxivCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        categories = self.config.get("categories", ["cs.AI"])
        max_results = self.config.get("max_results", 20)
        sort_by = self.config.get("sort_by", "submittedDate")

        query = " OR ".join(f"cat:{cat}" for cat in categories)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=getattr(arxiv.SortCriterion, sort_by, arxiv.SortCriterion.SubmittedDate),
        )

        client = arxiv.Client()
        results = list(client.results(search))
        return [self._parse_result(r) for r in results]

    def _parse_result(self, result) -> NewsItem:
        return NewsItem(
            source="arxiv",
            title=result.title.strip().replace("\n", " "),
            url=result.entry_id,
            content=result.summary.strip().replace("\n", " "),
            author=", ".join(a.name for a in result.authors),
            published_at=result.published,
            tags=result.categories,
            raw_data={
                "pdf_url": result.pdf_url,
                "categories": result.categories,
            },
        )
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_crawlers.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/crawlers/base.py src/crawlers/arxiv_crawler.py tests/test_crawlers.py
git commit -m "feat: BaseCrawler base class and arXiv crawler"
```

---

### Task 4: Reddit 爬虫

**Files:**
- Create: `src/crawlers/reddit_crawler.py`
- Modify: `tests/test_crawlers.py` — 追加 Reddit 测试

- [ ] **Step 1: 追加 Reddit 测试到 tests/test_crawlers.py**

```python
# 追加到 tests/test_crawlers.py

@patch("src.crawlers.reddit_crawler.praw")
def test_reddit_crawler_fetch(mock_praw):
    mock_reddit = MagicMock()
    mock_praw.Reddit.return_value = mock_reddit

    mock_submission = MagicMock()
    mock_submission.title = "New breakthrough in LLM"
    mock_submission.url = "https://reddit.com/r/MachineLearning/comments/abc"
    mock_submission.selftext = "Check out this new paper..."
    mock_submission.author.name = "ml_researcher"
    mock_submission.created_utc = 1713500400.0
    mock_submission.link_flair_text = "Research"
    mock_submission.score = 200
    mock_submission.num_comments = 50

    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [mock_submission]
    mock_reddit.subreddit.return_value = mock_subreddit

    crawler = RedditCrawler({
        "enabled": True,
        "subreddits": ["MachineLearning"],
        "sort": "hot",
        "limit": 10,
        "time_filter": "day",
    })

    items = crawler.fetch()
    assert len(items) >= 1
    assert items[0].source == "reddit"
    assert items[0].title == "New breakthrough in LLM"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_crawlers.py::test_reddit_crawler_fetch -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/crawlers/reddit_crawler.py**

```python
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_crawlers.py::test_reddit_crawler_fetch -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/crawlers/reddit_crawler.py tests/test_crawlers.py
git commit -m "feat: Reddit crawler via praw"
```

---

### Task 5: Twitter 爬虫 (Nitter RSS)

**Files:**
- Create: `src/crawlers/twitter_crawler.py`
- Modify: `tests/test_crawlers.py` — 追加 Twitter 测试

- [ ] **Step 1: 追加 Twitter 测试到 tests/test_crawlers.py**

```python
# 追加到 tests/test_crawlers.py

@patch("src.crawlers.twitter_crawler.feedparser")
@patch("src.crawlers.twitter_crawler.requests.get")
def test_twitter_crawler_fetch(mock_get, mock_feedparser):
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = "<rss>fake rss</rss>"

    mock_feedparser.parse.return_value = {
        "entries": [
            {
                "title": "Exciting AI update from OpenAI!",
                "link": "https://nitter.net/OpenAI/status/123",
                "summary": "We are releasing a new model...",
                "author": "@OpenAI",
                "published": "Fri, 18 Apr 2026 12:00:00 GMT",
            }
        ]
    }

    crawler = TwitterCrawler({
        "enabled": True,
        "nitter_instances": ["https://nitter.net"],
        "accounts": ["OpenAI"],
        "limit": 10,
    })

    items = crawler.fetch()
    assert len(items) >= 1
    assert items[0].source == "twitter"
    assert items[0].title == "Exciting AI update from OpenAI!"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_crawlers.py::test_twitter_crawler_fetch -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/crawlers/twitter_crawler.py**

```python
# src/crawlers/twitter_crawler.py
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests
from loguru import logger

from src.crawlers.base import BaseCrawler
from src.models import NewsItem


class TwitterCrawler(BaseCrawler):
    def fetch(self) -> list[NewsItem]:
        instances = self.config.get("nitter_instances", ["https://nitter.net"])
        accounts = self.config.get("accounts", [])
        limit = self.config.get("limit", 20)

        items = []
        for account in accounts:
            rss_url = f"{self._pick_instance(instances)}/{account}/rss"
            try:
                resp = requests.get(rss_url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning(f"Twitter: failed to fetch @{account}: {e}")
                continue

            feed = feedparser.parse(resp.text)
            for entry in feed.get("entries", [])[:limit]:
                try:
                    pub_date = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    pub_date = datetime.now(timezone.utc)

                items.append(NewsItem(
                    source="twitter",
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    content=entry.get("summary", ""),
                    author=entry.get("author", account),
                    published_at=pub_date,
                    tags=["twitter"],
                    raw_data={"account": account},
                ))

        return items

    def _pick_instance(self, instances: list[str]) -> str:
        """选第一个可用的 Nitter 实例。"""
        return instances[0] if instances else "https://nitter.net"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_crawlers.py::test_twitter_crawler_fetch -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/crawlers/twitter_crawler.py tests/test_crawlers.py
git commit -m "feat: Twitter crawler via Nitter RSS"
```

---

### Task 6: LLM 客户端 (多 provider)

**Files:**
- Create: `src/llm/client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: 写 test_llm_client.py**

```python
# tests/test_llm_client.py
from unittest.mock import patch, MagicMock
from src.llm.client import LLMClient


def test_llm_client_uses_default_provider():
    config = {
        "default": "openai",
        "providers": {
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        },
    }
    client = LLMClient(config)
    assert client.provider == "openai"
    assert client.model == "gpt-4o"


def test_llm_client_generate(monkeypatch):
    config = {
        "default": "openai",
        "providers": {
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        },
    }
    client = LLMClient(config)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Generated article content"

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = mock_response

        result = client.generate("system prompt", "user prompt")
        assert result == "Generated article content"


def test_llm_client_anthropic_generate(monkeypatch):
    config = {
        "default": "anthropic",
        "providers": {
            "anthropic": {
                "api_key": "sk-ant-test",
                "base_url": "https://api.anthropic.com",
                "model": "claude-sonnet-4-6-20250514",
            }
        },
    }
    client = LLMClient(config)

    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Claude generated content"

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_anthropic = MagicMock()
        mock_anthropic_cls.return_value = mock_anthropic
        mock_anthropic.messages.create.return_value = mock_response

        result = client.generate("system prompt", "user prompt")
        assert result == "Claude generated content"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_llm_client.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/llm/client.py**

```python
# src/llm/client.py
from loguru import logger


class LLMClient:
    def __init__(self, config: dict):
        self.config = config
        self.provider = config.get("default", "openai")
        self._provider_config = config.get("providers", {}).get(self.provider, {})
        self.api_key = self._provider_config.get("api_key", "")
        self.base_url = self._provider_config.get("base_url", "")
        self.model = self._provider_config.get("model", "")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "anthropic":
            return self._generate_anthropic(system_prompt, user_prompt)
        return self._generate_openai_compatible(system_prompt, user_prompt)

    def _generate_openai_compatible(self, system_prompt: str, user_prompt: str) -> str:
        import openai

        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    def _generate_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_llm_client.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/llm/client.py tests/test_llm_client.py
git commit -m "feat: unified LLM client supporting OpenAI and Anthropic"
```

---

### Task 7: Prompt 模板 + 加载器

**Files:**
- Create: `src/llm/prompts.py`
- Create: `prompts/daily.md`
- Create: `prompts/weekly.md`
- Test: `tests/test_llm_client.py` — 追加 prompt 测试

- [ ] **Step 1: 追加 prompt 测试到 tests/test_llm_client.py**

```python
# 追加到 tests/test_llm_client.py
import os
import tempfile
from src.llm.prompts import load_prompt


def test_load_prompt_renders_template():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.md")
        with open(path, "w") as f:
            f.write("Hello {{name}}, today is {{date}}.")

        result = load_prompt("test", name="World", date="2026-04-19", prompts_dir=tmpdir)
        assert result == "Hello World, today is 2026-04-19."
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_llm_client.py::test_load_prompt_renders_template -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/llm/prompts.py**

```python
# src/llm/prompts.py
import re
from pathlib import Path


def load_prompt(name: str, prompts_dir: str = None, **kwargs) -> str:
    """加载 prompts/{name}.md 模板，替换 {{key}} 占位符。"""
    if prompts_dir is None:
        prompts_dir = Path(__file__).parent.parent.parent / "prompts"
    else:
        prompts_dir = Path(prompts_dir)

    path = prompts_dir / f"{name}.md"
    template = path.read_text(encoding="utf-8")

    def replacer(match):
        key = match.group(1)
        return str(kwargs.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)
```

- [ ] **Step 4: 创建 Prompt 模板**

```markdown
<!-- prompts/daily.md -->
你是一位资深 AI 科技编辑。请根据以下今日新闻素材，撰写一篇面向微信公众号的每日 AI 科技快讯文章。

要求：
1. 标题：吸引眼球，包含日期，20字以内
2. 导语：100字概括今日要点
3. 正文：每条新闻用「## 新闻标题」格式，包含 200-300 字中文解读
4. 结语：50字总结展望
5. 语气：专业但易懂，适合科技从业者阅读
6. 不使用 Markdown 代码块和表格，使用公众号友好的格式

日期：{{date}}
新闻素材：

{{news_content}}
```

```markdown
<!-- prompts/weekly.md -->
你是一位资深 AI 科技编辑。请根据以下本周新闻素材，撰写一篇面向微信公众号的每周 AI 科技深度汇总文章。

要求：
1. 标题：包含日期范围，体现深度分析感，25字以内
2. 导语：150字概述本周 AI 领域重大进展
3. 正文：将新闻按主题分组（如「大模型」「计算机视觉」「开源项目」「行业动态」），每组用「## 主题名」格式，每条新闻 300-500 字深度解读，包含技术分析和行业影响
4. 本周总结：100字回顾本周趋势
5. 下周展望：50字预判下周热点
6. 语气：专业深入，适合 AI 从业者和研究者阅读
7. 不使用 Markdown 代码块和表格，使用公众号友好的格式

日期范围：{{date}}
新闻素材：

{{news_content}}
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_llm_client.py::test_load_prompt_renders_template -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/llm/prompts.py prompts/ tests/test_llm_client.py
git commit -m "feat: prompt template loader with daily and weekly templates"
```

---

### Task 8: TTS 引擎 (edge-tts)

**Files:**
- Create: `src/tts/engine.py`
- Test: `tests/test_tts.py`

- [ ] **Step 1: 写 test_tts.py**

```python
# tests/test_tts.py
import os
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock

from src.tts.engine import TTSEngine


def test_tts_engine_init():
    config = {
        "default": "edge-tts",
        "edge-tts": {
            "voice": "zh-CN-YunxiNeural",
            "rate": "+0%",
            "output_format": "mp3",
        },
    }
    engine = TTSEngine(config)
    assert engine.voice == "zh-CN-YunxiNeural"
    assert engine.rate == "+0%"


@patch("src.tts.engine.edge_tts")
def test_tts_engine_generate(mock_edge_tts):
    config = {
        "default": "edge-tts",
        "edge-tts": {
            "voice": "zh-CN-YunxiNeural",
            "rate": "+0%",
            "output_format": "mp3",
        },
    }
    engine = TTSEngine(config)

    mock_communicate = MagicMock()
    mock_edge_tts.Communicate.return_value = mock_communicate

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "test.mp3")
        # 创建一个假 MP3 文件让 save 正常运行
        with open(output_path, "wb") as f:
            f.write(b"fake mp3")

        mock_communicate.save.sync_side_effect = lambda path, **kw: open(path, "wb").write(b"fake mp3") or None

        result = engine.generate("测试文本", output_path)
        assert os.path.exists(result)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_tts.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/tts/engine.py**

```python
# src/tts/engine.py
import asyncio
from pathlib import Path

import edge_tts
from loguru import logger


class TTSEngine:
    def __init__(self, config: dict):
        tts_config = config.get(config.get("default", "edge-tts"), {})
        self.voice = tts_config.get("voice", "zh-CN-YunxiNeural")
        self.rate = tts_config.get("rate", "+0%")
        self.output_format = tts_config.get("output_format", "mp3")

    def generate(self, text: str, output_path: str) -> str:
        """将文本转为音频文件，返回输出路径。"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)

        if asyncio.get_event_loop().is_running():
            # 如果已在异步上下文中，用新线程
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, communicate.save(output_path))
                future.result()
        else:
            asyncio.run(communicate.save(output_path))

        logger.info(f"TTS audio saved to {output_path}")
        return output_path
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_tts.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/tts/engine.py tests/test_tts.py
git commit -m "feat: TTS engine using edge-tts"
```

---

### Task 9: 微信公众号发布器

**Files:**
- Create: `src/publish/wechat.py`
- Test: `tests/test_publish.py`

- [ ] **Step 1: 写 test_publish.py**

```python
# tests/test_publish.py
from unittest.mock import patch, MagicMock
from src.publish.wechat import WeChatPublisher


def test_wechat_get_access_token():
    config = {
        "app_id": "wx123",
        "app_secret": "secret123",
    }
    publisher = WeChatPublisher(config)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "token_abc", "expires_in": 7200}
    mock_resp.raise_for_status = MagicMock()

    with patch("src.publish.wechat.requests.get", return_value=mock_resp):
        token = publisher._get_access_token()
        assert token == "token_abc"


@patch("src.publish.wechat.requests.post")
@patch("src.publish.wechat.requests.get")
def test_wechat_upload_audio(mock_get, mock_post):
    config = {"app_id": "wx123", "app_secret": "secret123"}
    publisher = WeChatPublisher(config)

    # mock token
    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "tok123", "expires_in": 7200}
    mock_token_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_token_resp

    # mock upload
    mock_upload_resp = MagicMock()
    mock_upload_resp.json.return_value = {"media_id": "media_abc"}
    mock_upload_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_upload_resp

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"fake mp3")
        audio_path = f.name

    try:
        media_id = publisher.upload_audio(audio_path)
        assert media_id == "media_abc"
    finally:
        os.unlink(audio_path)


@patch("src.publish.wechat.requests.post")
@patch("src.publish.wechat.requests.get")
def test_wechat_publish_article(mock_get, mock_post):
    config = {"app_id": "wx123", "app_secret": "secret123"}
    publisher = WeChatPublisher(config)

    # mock token
    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "tok123", "expires_in": 7200}
    mock_token_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_token_resp

    # mock draft + publish
    mock_draft_resp = MagicMock()
    mock_draft_resp.json.return_value = {"media_id": "draft_123"}
    mock_draft_resp.raise_for_status = MagicMock()

    mock_pub_resp = MagicMock()
    mock_pub_resp.json.return_value = {"publish_id": "pub_123"}
    mock_pub_resp.raise_for_status = MagicMock()

    mock_post.side_effect = [mock_draft_resp, mock_pub_resp]

    result = publisher.publish_article(
        title="AI 日报",
        content="<p>Test content</p>",
        audio_media_id="media_abc",
        thumb_media_id="thumb_abc",
    )
    assert result == "pub_123"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_publish.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/publish/wechat.py**

```python
# src/publish/wechat.py
import time
from pathlib import Path

import requests
from loguru import logger


class WeChatPublisher:
    BASE_URL = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, config: dict):
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self._token = None
        self._token_expires = 0

    def _get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token

        url = f"{self.BASE_URL}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise RuntimeError(f"WeChat API error: {data}")

        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 7200) - 300
        logger.info("WeChat access_token refreshed")
        return self._token

    def upload_audio(self, audio_path: str) -> str:
        """上传音频为永久素材，返回 media_id。"""
        token = self._get_access_token()
        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "voice"}

        with open(audio_path, "rb") as f:
            files = {"media": (Path(audio_path).name, f, "audio/mpeg")}
            resp = requests.post(url, params=params, files=files)
        resp.raise_for_status()
        data = resp.json()

        if "media_id" not in data:
            raise RuntimeError(f"WeChat upload audio failed: {data}")

        logger.info(f"Audio uploaded, media_id={data['media_id']}")
        return data["media_id"]

    def upload_thumb(self, image_path: str) -> str:
        """上传缩略图（封面），返回 media_id。"""
        token = self._get_access_token()
        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "image"}

        with open(image_path, "rb") as f:
            files = {"media": (Path(image_path).name, f, "image/jpeg")}
            resp = requests.post(url, params=params, files=files)
        resp.raise_for_status()
        data = resp.json()

        if "media_id" not in data:
            raise RuntimeError(f"WeChat upload thumb failed: {data}")

        return data["media_id"]

    def publish_article(
        self,
        title: str,
        content: str,
        audio_media_id: str = "",
        thumb_media_id: str = "",
    ) -> str:
        """创建草稿并发布，返回 publish_id。"""
        token = self._get_access_token()

        # 如果有音频，追加到文章内容末尾
        body = content
        if audio_media_id:
            body += f'\n<mpvoice voice_encode_fileid="{audio_media_id}" />'

        # 创建草稿
        draft_url = f"{self.BASE_URL}/draft/add"
        draft_data = {
            "access_token": token,
            "articles": [
                {
                    "title": title,
                    "author": "AI科技前沿",
                    "content": body,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 1,
                }
            ],
        }
        resp = requests.post(draft_url, json=draft_data)
        resp.raise_for_status()
        draft = resp.json()

        if "media_id" not in draft:
            raise RuntimeError(f"WeChat create draft failed: {draft}")

        logger.info(f"Draft created, media_id={draft['media_id']}")

        # 发布
        pub_url = f"{self.BASE_URL}/freepublish/submit"
        pub_data = {"access_token": token, "media_id": draft["media_id"]}
        resp = requests.post(pub_url, json=pub_data)
        resp.raise_for_status()
        pub = resp.json()

        if "publish_id" not in pub:
            raise RuntimeError(f"WeChat publish failed: {pub}")

        logger.info(f"Article published, publish_id={pub['publish_id']}")
        return pub["publish_id"]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_publish.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/publish/wechat.py tests/test_publish.py
git commit -m "feat: WeChat MP publisher with draft and publish API"
```

---

### Task 10: Pipeline 编排器

**Files:**
- Create: `src/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 写 test_pipeline.py**

```python
# tests/test_pipeline.py
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.models import NewsItem
from src.pipeline import Pipeline


def _make_items(n):
    return [
        NewsItem(
            source="test",
            title=f"News {i}",
            url=f"https://example.com/{i}",
            content=f"Content {i}",
            author="Author",
            published_at=datetime.now(timezone.utc),
            tags=["AI"],
            raw_data={},
        )
        for i in range(n)
    ]


def test_pipeline_deduplicate():
    items = _make_items(3)
    items.append(items[0])  # duplicate

    deduped = Pipeline._deduplicate(items)
    assert len(deduped) == 3


def test_pipeline_format_news():
    items = _make_items(2)
    text = Pipeline._format_news(items)
    assert "News 0" in text
    assert "News 1" in text


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_run_daily(mock_llm_cls, mock_tts_cls, mock_wechat_cls):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "<h1>AI 日报</h1><p>Content</p>"
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts.generate.return_value = "/tmp/test.mp3"
    mock_tts_cls.return_value = mock_tts

    mock_wechat = MagicMock()
    mock_wechat.upload_audio.return_value = "media_123"
    mock_wechat.publish_article.return_value = "pub_123"
    mock_wechat_cls.return_value = mock_wechat

    mock_crawler = MagicMock()
    mock_crawler.fetch.return_value = _make_items(3)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[mock_crawler],
        llm_client=mock_llm,
        tts_engine=mock_tts,
        publisher=mock_wechat,
    )

    result = pipeline.run()
    assert result is True
    mock_llm.generate.assert_called_once()
    mock_tts.generate.assert_called_once()
    mock_wechat.publish_article.assert_called_once()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/pipeline.py**

```python
# src/pipeline.py
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.llm.client import LLMClient
from src.llm.prompts import load_prompt
from src.models import NewsItem
from src.publish.wechat import WeChatPublisher
from src.tts.engine import TTSEngine


class Pipeline:
    def __init__(
        self,
        mode: str,
        crawlers: list,
        llm_client: LLMClient,
        tts_engine: TTSEngine,
        publisher: WeChatPublisher,
    ):
        self.mode = mode  # "daily" or "weekly"
        self.crawlers = crawlers
        self.llm = llm_client
        self.tts = tts_engine
        self.publisher = publisher

    def run(self) -> bool:
        """执行完整管道：爬取 → LLM → TTS → 发布。返回是否成功。"""
        try:
            # 1. 爬取
            logger.info(f"Pipeline [{self.mode}]: crawling...")
            all_items = []
            for crawler in self.crawlers:
                try:
                    items = crawler.fetch()
                    logger.info(f"  {crawler.name}: {len(items)} items")
                    all_items.extend(items)
                except Exception as e:
                    logger.error(f"  {crawler.name} failed: {e}")

            if not all_items:
                logger.warning("No news items fetched, aborting pipeline")
                return False

            # 2. 去重
            all_items = self._deduplicate(all_items)
            logger.info(f"After dedup: {len(all_items)} items")

            # 3. LLM 生成文章
            logger.info("Generating article via LLM...")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            news_text = self._format_news(all_items)
            template_name = "daily" if self.mode == "daily" else "weekly"

            system_prompt = load_prompt(template_name, date=today, news_content=news_text)
            article_html = self.llm.generate(system_prompt, news_text)

            # 保存文章
            output_dir = Path("output/articles")
            output_dir.mkdir(parents=True, exist_ok=True)
            article_path = output_dir / f"{self.mode}_{today}.html"
            article_path.write_text(article_html, encoding="utf-8")
            logger.info(f"Article saved to {article_path}")

            # 4. TTS 生成音频
            logger.info("Generating audio via TTS...")
            # 去掉 HTML 标签用于 TTS
            clean_text = self._strip_html(article_html)
            audio_dir = Path("output/audio")
            audio_dir.mkdir(parents=True, exist_ok=True)
            audio_path = str(audio_dir / f"{self.mode}_{today}.mp3")
            self.tts.generate(clean_text, audio_path)

            # 5. 发布
            logger.info("Publishing to WeChat...")
            audio_media_id = self.publisher.upload_audio(audio_path)
            title = f"AI 科技前沿 | {today}"
            publish_id = self.publisher.publish_article(
                title=title,
                content=article_html,
                audio_media_id=audio_media_id,
            )
            logger.info(f"Published successfully, publish_id={publish_id}")
            return True

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            return False

    @staticmethod
    def _deduplicate(items: list[NewsItem]) -> list[NewsItem]:
        """按标题去重。"""
        seen = set()
        result = []
        for item in items:
            normalized = item.title.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                result.append(item)
        return result

    @staticmethod
    def _format_news(items: list[NewsItem]) -> str:
        """将新闻列表格式化为文本，供 LLM 使用。"""
        parts = []
        for i, item in enumerate(items, 1):
            parts.append(
                f"【{i}】来源: {item.source} | 标题: {item.title}\n"
                f"作者: {item.author} | 时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"链接: {item.url}\n"
                f"内容: {item.content[:500]}\n"
                f"标签: {', '.join(item.tags) if item.tags else '无'}\n"
            )
        return "\n---\n".join(parts)

    @staticmethod
    def _strip_html(html: str) -> str:
        """简单移除 HTML 标签，用于 TTS 朗读。"""
        import re
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_pipeline.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestrator with crawl, LLM, TTS, and publish"
```

---

### Task 11: 主入口 main.py

**Files:**
- Create: `main.py`

- [ ] **Step 1: 实现 main.py**

```python
# main.py
import sys
from datetime import datetime, timezone

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

    # 加载配置
    sources_config = load_config("sources")
    llm_config = load_config("llm")
    tts_config = load_config("tts")
    wechat_config = load_config("wechat")

    # 构建组件
    crawlers = build_crawlers(sources_config)
    llm_client = LLMClient(llm_config)
    tts_engine = TTSEngine(tts_config)

    if mode == "test":
        # 测试模式：只爬取不发布
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

    # 执行管道
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
```

- [ ] **Step 2: 运行所有测试验证**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 3: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add main.py
git commit -m "feat: main entry point with daily, weekly, and test modes"
```

---

### Task 12: 端到端集成测试

**Files:**
- Modify: `tests/test_pipeline.py` — 追加集成测试

- [ ] **Step 1: 追加集成测试到 tests/test_pipeline.py**

```python
# 追加到 tests/test_pipeline.py

@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_crawler_failure_continues(mock_llm_cls, mock_tts_cls, mock_wechat_cls):
    """某个爬虫失败不影响其他爬虫。"""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "<p>article</p>"
    mock_llm_cls.return_value = mock_llm

    mock_tts = MagicMock()
    mock_tts.generate.return_value = "/tmp/test.mp3"
    mock_tts_cls.return_value = mock_tts

    mock_wechat = MagicMock()
    mock_wechat.upload_audio.return_value = "media_123"
    mock_wechat.publish_article.return_value = "pub_123"
    mock_wechat_cls.return_value = mock_wechat

    failing_crawler = MagicMock()
    failing_crawler.name = "FailingCrawler"
    failing_crawler.fetch.side_effect = Exception("Network error")

    working_crawler = MagicMock()
    working_crawler.name = "WorkingCrawler"
    working_crawler.fetch.return_value = _make_items(2)

    pipeline = Pipeline(
        mode="daily",
        crawlers=[failing_crawler, working_crawler],
        llm_client=mock_llm,
        tts_engine=mock_tts,
        publisher=mock_wechat,
    )

    result = pipeline.run()
    assert result is True
    mock_llm.generate.assert_called_once()


@patch("src.pipeline.WechatPublisher")
@patch("src.pipeline.TTSEngine")
@patch("src.pipeline.LLMClient")
def test_pipeline_no_items_returns_false(mock_llm_cls, mock_tts_cls, mock_wechat_cls):
    """没有爬取到任何内容时中止管道。"""
    mock_llm = MagicMock()
    mock_llm_cls.return_value = mock_llm

    empty_crawler = MagicMock()
    empty_crawler.name = "EmptyCrawler"
    empty_crawler.fetch.return_value = []

    pipeline = Pipeline(
        mode="daily",
        crawlers=[empty_crawler],
        llm_client=mock_llm,
        tts_engine=MagicMock(),
        publisher=MagicMock(),
    )

    result = pipeline.run()
    assert result is False
    mock_llm.generate.assert_not_called()
```

- [ ] **Step 2: 运行所有测试**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 3: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add tests/test_pipeline.py
git commit -m "test: integration tests for pipeline error handling"
```

---

### Task 13: Cron 定时任务配置

**Files:**
- Create: `setup_cron.sh`

- [ ] **Step 1: 创建 setup_cron.sh**

```bash
#!/bin/bash
# setup_cron.sh — 设置定时任务

PROJECT_DIR="/home/zhangfy/gongzhonghao"
PYTHON="$(which python3)"

echo "Setting up cron jobs for AI news pipeline..."
echo ""

# 每日 8:00 执行
(crontab -l 2>/dev/null; echo "0 8 * * * cd $PROJECT_DIR && $PYTHON main.py daily >> logs/cron.log 2>&1") | sort -u | crontab -

# 每周日 10:00 执行
(crontab -l 2>/dev/null; echo "0 10 * * 0 cd $PROJECT_DIR && $PYTHON main.py weekly >> logs/cron.log 2>&1") | sort -u | crontab -

echo "Cron jobs installed:"
crontab -l | grep gongzhonghao
echo ""
echo "Done! Use 'crontab -l' to verify."
```

- [ ] **Step 2: 运行所有测试确认全绿**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 3: 提交**

```bash
cd /home/zhangfy/gongzhonghao
git add setup_cron.sh
git commit -m "feat: cron setup script for daily and weekly scheduling"
```

---

## 前置准备清单（用户操作）

在运行系统前需要完成：

1. **公众号 API** — 登录 mp.weixin.qq.com → 开发 → 基本配置，获取 AppID + AppSecret
2. **IP 白名单** — 公众号后台将你的公网 IP 加入白名单
3. **确认公众号类型** — 服务号/订阅号（影响 API 权限）
4. **Reddit API** — reddit.com/prefs/apps 创建 script 类型 App，获取 client_id 和 client_secret
5. **LLM API Key** — 准备 OpenAI 或 Anthropic 的 API Key
6. **配置 .env** — 复制 `.env.example` 为 `.env`，填入所有凭证
7. **测试运行** — `python main.py test` 先验证爬虫正常工作
