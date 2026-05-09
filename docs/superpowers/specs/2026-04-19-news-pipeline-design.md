# AI 科技前沿公众号自动化系统设计

## 概述

构建一个 Python 管道式自动化系统，定期从 arXiv、Reddit、Twitter 爬取 AI/科技领域新闻，通过 LLM 整理成中文文章，生成 TTS 音频，全自动发布到微信公众号。

支持每日快讯（每天 8:00）和每周深度汇总（每周日 10:00）两种模式。

## 架构

```
Cron 定时调度
    → Pipeline 编排器 (pipeline.py)
        → 爬虫层 (crawlers/)   — 多源采集，统一输出
        → LLM 层 (llm/)        — 多 provider，生成文章
        → TTS 层 (tts/)        — edge-tts 生成音频
        → 发布层 (publish/)     — 公众号 API 全自动发布
```

配置驱动，模块解耦。任何步骤失败则中止后续流程，记录日志。

## 数据流

1. 各爬虫并行采集，输出统一 `NewsItem` 结构
2. LLM 去重 → 生成摘要 → 组装文章（HTML + Markdown）
3. edge-tts 将文章转为 MP3 音频
4. 通过公众号 API 上传素材 → 创建草稿 → 发布
5. 发布结果通知

## 模块设计

### 爬虫层

统一数据结构：

```python
@dataclass
class NewsItem:
    source: str          # "arxiv" / "reddit" / "twitter"
    title: str
    url: str
    content: str
    author: str
    published_at: datetime
    tags: list[str]
    raw_data: dict
```

| 来源 | 方式 | 说明 |
|------|------|------|
| arXiv | 官方 API (`arxiv` Python 包) | 按分类 (cs.AI, cs.CL) 检索 |
| Reddit | `praw` (官方 API) | 抓取 r/MachineLearning 等 |
| Twitter | Nitter RSS / `snscrape` | 替代收费的 Twitter API |

部分爬虫失败不影响其他源。

### LLM 层

多 provider 配置，支持 OpenAI / Anthropic / 自定义 endpoint：

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

处理步骤：去重过滤 → 摘要生成 → 文章组装 → 标签分类。

Prompt 模板存放于 `prompts/` 目录，区分每日快讯和每周深度两种风格。

### TTS 层

使用 `edge-tts`（微软 Edge TTS Python 封装）：

- 免费，无需 API Key
- 高质量中文语音（zh-CN-YunxiNeural 等）
- 直接输出 MP3，符合公众号音频格式要求

### 发布层

公众号 API 流程：获取 access_token → 上传音频素材 → 上传封面图 → 创建草稿 → 发布。

降级方案：若 API 权限不足（订阅号限制），则生成 HTML + MP3 文件，通过浏览器自动化或手动上传。

## 项目结构

```
gongzhonghao/
├── config/
│   ├── sources.yaml
│   ├── llm.yaml
│   ├── tts.yaml
│   ├── wechat.yaml
│   └── schedule.yaml
├── src/
│   ├── crawlers/
│   │   ├── base.py
│   │   ├── arxiv.py
│   │   ├── reddit.py
│   │   └── twitter.py
│   ├── llm/
│   │   ├── client.py
│   │   └── prompts.py
│   ├── tts/
│   │   └── engine.py
│   ├── publish/
│   │   └── wechat.py
│   └── pipeline.py
├── prompts/
│   ├── daily.md
│   └── weekly.md
├── output/
│   ├── articles/
│   └── audio/
├── logs/
├── main.py
├── requirements.txt
├── .env
└── .env.example
```

## 调度

系统 cron 调用 `python main.py daily` / `python main.py weekly`：

```
0 8 * * * cd /home/zhangfy/gongzhonghao && python main.py daily
0 10 * * 0 cd /home/zhangfy/gongzhonghao && python main.py weekly
```

## 错误处理

- 各模块独立 try/catch，失败中止后续步骤
- 日志按日期滚动写入 `logs/`
- 发布失败自动重试 1 次
- 爬虫部分失败不影响其他源

## 前置准备

| 序号 | 事项 | 操作 |
|------|------|------|
| 1 | 公众号 API 凭证 | mp.weixin.qq.com → 开发 → 基本配置 |
| 2 | IP 白名单 | 公众号后台配置公网 IP |
| 3 | 确认公众号类型 | 确认服务号/订阅号 |
| 4 | Reddit API 凭证 | reddit.com/prefs/apps 创建 script App |
| 5 | LLM API Key | 准备 OpenAI/Anthropic API Key |
| 6 | Python 依赖 | pip install -r requirements.txt |
