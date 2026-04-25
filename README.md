# AI Daily Bot

AI 科技新闻自动聚合与发布系统，每日自动爬取 AI 领域新闻，通过 LLM 生成文章，配图后发布到微信公众号。

## 功能

- **多源爬取**：arXiv、Reddit、Twitter（Nitter RSS）、HuggingFace Papers、GitHub、中国 AI 媒体（量子位/智东西/雷锋网）
- **LLM 生成**：支持 OpenAI / Anthropic / 自定义兼容接口，自动生成中文文章
- **官方验证**：精选模式下，通过官网、微信公众号、官方推特、CEO 推特、模型负责人推特逐级验证新闻真实性，超过 24h 自动舍弃
- **智能配图**：优先从官方来源抓取图表，其次使用 gpt-image-2 生成插图
- **微信发布**：自动上传封面图和文章图片，创建草稿

## 运行模式

```bash
# 每日快讯（10-15 条新闻汇总）
python main.py daily

# 精选深度（Top 5 单篇深度文章，需官方验证）
python main.py feature

# 周报
python main.py weekly

# 调试模式（爬取+生成，不生图不发布）
python main.py daily --debug
python main.py feature --debug

# 仅爬取测试
python main.py test

# 手动标记已发布（关键词去重）
python main.py mark-published 2026-04-25
```

## 配置

所有配置文件在 `config/` 目录下：

| 文件 | 说明 |
|------|------|
| `sources.yaml` | 各爬虫开关和参数 |
| `llm.yaml` | LLM 提供商配置（支持多个） |
| `wechat.yaml` | 微信公众号 AppID/Secret |
| `official_sources.yaml` | AI 公司官方渠道映射（用于验证） |

敏感信息通过环境变量注入：

```bash
export CUSTOM_API_KEY=xxx
export VISION_API_KEY=xxx
export IMAGE_API_KEY=xxx
export WECHAT_APP_ID=xxx
export WECHAT_APP_SECRET=xxx
```

或写入 `.env` 文件（已加入 .gitignore）。

## 定时任务

```bash
bash setup_cron.sh
```

每天 7:30 自动执行 daily 模式，每周日 10:00 执行 weekly 模式。

## 项目结构

```
├── main.py                 # 入口
├── config/                 # YAML 配置
├── prompts/                # LLM 提示词模板
│   ├── daily.md            # 日报模板
│   ├── feature.md          # 精选深度模板
│   ├── weekly.md           # 周报模板
│   └── selector.md         # 新闻筛选模板
├── src/
│   ├── crawlers/           # 各来源爬虫
│   ├── llm/                # LLM 客户端
│   ├── image/              # 图片生成
│   ├── publish/            # 微信发布
│   ├── tts/                # 语音合成
│   ├── pipeline.py         # 主流程编排
│   ├── pipeline_cache.py   # 去重与图片缓存
│   └── verifier.py         # 官方来源验证
└── output/                 # 生成产物（已 gitignore）
```

## 依赖

```bash
pip install loguru requests beautifulsoup4 feedparser arxiv edge-tts openai anthropic PyYAML lxml
```

需要 Python 3.10+。
