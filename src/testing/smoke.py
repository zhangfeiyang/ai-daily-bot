from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import MethodType
import json
import os
import re

from src.models import NewsItem
from src.pipeline import Pipeline

_BEIJING_TZ = timezone(timedelta(hours=8))


@dataclass
class SmokeResult:
    success: bool
    workdir: str
    article_path: str
    html: str
    llm_generate_calls: int
    tts_calls: int
    publish_calls: int
    inserted_images: int
    inserted_videos: int
    title: str
    thumb_media_id: str
    audio_paths: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class SmokeLLM:
    def __init__(self, article_markdown: str):
        self.article_markdown = article_markdown
        self.generate_calls: list[dict] = []
        self.image_calls: list[dict] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.generate_calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        if "去AI味" in system_prompt or "资深中文编辑" in system_prompt:
            return user_prompt
        return self.article_markdown

    def generate_with_images(self, system_prompt: str, text: str, image_urls: list[str], provider: str = "vision") -> str:
        self.image_calls.append(
            {
                "system_prompt": system_prompt,
                "text": text,
                "image_urls": list(image_urls),
                "provider": provider,
            }
        )
        return "YES"


class SmokeTTS:
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.calls: list[dict] = []

    def generate(self, text: str, output_path: str) -> str:
        self.calls.append({"text": text, "output_path": output_path})
        audio_path = Path(f"{output_path}.mp3")
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"smoke-audio")
        return str(audio_path)


class SmokePublisher:
    def __init__(self):
        self.publish_calls: list[dict] = []
        self.draft_calls: list[dict] = []

    def create_draft(
        self,
        title: str,
        content: str,
        audio_paths: list[str] | None = None,
        audio_path: str = "",
        thumb_media_id: str = "",
    ) -> str:
        if audio_path and not audio_paths:
            audio_paths = [audio_path]
        self.draft_calls.append(
            {
                "title": title,
                "content": content,
                "audio_paths": list(audio_paths or []),
                "thumb_media_id": thumb_media_id,
            }
        )
        return "smoke-draft-001"

    def publish_article(
        self,
        title: str,
        content: str,
        audio_paths: list[str] | None = None,
        audio_path: str = "",
        thumb_media_id: str = "",
    ) -> str:
        if audio_path and not audio_paths:
            audio_paths = [audio_path]
        self.publish_calls.append(
            {
                "title": title,
                "content": content,
                "audio_paths": list(audio_paths or []),
                "thumb_media_id": thumb_media_id,
            }
        )
        return "smoke-publish-001"


class SmokeCrawler:
    name = "SmokeCrawler"

    def fetch(self) -> list[NewsItem]:
        now = datetime.now(timezone.utc)
        return [
            NewsItem(
                source="smoke",
                title="OpenAI Codex 终于会看图了",
                url="https://example.com/openai-codex",
                content="Codex 这次更像一个真正的开发搭档，而不只是补全工具。",
                author="SmokeLab",
                published_at=now,
                tags=["smoke", "codex"],
                raw_data={
                    "image_url": "https://assets.example.com/openai-codex.png",
                    "links": ["https://openai.com/index/"],
                },
            ),
            NewsItem(
                source="smoke",
                title="DeepSeek 把推理成本再往下压",
                url="https://example.com/deepseek-reasoning",
                content="这类更新的重点不是口号，而是开发者能不能真省钱。",
                author="SmokeLab",
                published_at=now,
                tags=["smoke", "deepseek"],
                raw_data={
                    "video_urls": ["https://cdn.example.com/deepseek-demo.mp4"],
                    "links": ["https://deepseek.com/"],
                },
            ),
            NewsItem(
                source="smoke",
                title="Google Gemini 开始接管办公流",
                url="https://example.com/google-gemini",
                content="当模型直接接到文档和表格，办公软件的边界会变模糊。",
                author="SmokeLab",
                published_at=now,
                tags=["smoke", "gemini"],
                raw_data={
                    "image_url": "https://assets.example.com/gemini-office.png",
                    "links": ["https://blog.google/"],
                },
            ),
        ]


def _article_markdown(items: list[NewsItem]) -> str:
    today = datetime.now(_BEIJING_TZ).strftime("%m%d")
    lines = [
        f"# {today}：AI 圈今天有三件事值得盯着",
        "",
        "这不是那种只会堆术语的日报。今天的重点很简单：能省钱、能干活、能落地。",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"## {item.title}",
                "先说结论：这类更新的价值，通常不在参数表，而在工作流里少走几步。",
                f"**参考链接：** {item.url} {item.raw_data.get('links', [''])[0]}".strip(),
                "",
            ]
        )
    lines.extend(
        [
            "结语：AI 更新越来越像实用工具，而不是发布会上的口号。真正重要的是它能不能进入日常工作。",
            "",
        ]
    )
    return "\n".join(lines)


def run_smoke_pipeline(workdir: str | Path) -> SmokeResult:
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    old_cwd = Path.cwd()
    os.chdir(workdir)
    try:
        crawler = SmokeCrawler()
        items = crawler.fetch()

        llm = SmokeLLM(_article_markdown(items))
        tts = SmokeTTS(workdir)
        publisher = SmokePublisher()

        pipeline = Pipeline(
            mode="daily",
            crawlers=[crawler],
            llm_client=llm,
            tts_engine=tts,
            publisher=publisher,
            debug=False,
        )

        def fake_fetch_page_assets(self, url: str):
            return [], [], []

        def fake_generate_cover(self, today: str, items: list[NewsItem], article_text: str) -> str:
            return "thumb_smoke_001"

        def fake_download_and_upload_image(self, image_url: str, title: str, cache_namespace: str = "") -> str:
            return (
                '<section style="text-align:center;margin:12px 0;">'
                f'<img src="{image_url}" style="max-width:100%;border-radius:8px;" />'
                "</section>"
            )

        def fake_download_and_render_video(self, video_url: str, title: str) -> str:
            return (
                '<section style="text-align:center;margin:12px 0;">'
                f'<video src="{video_url}" controls="controls" style="max-width:100%;border-radius:8px;"></video>'
                "</section>"
            )

        def fake_generate_section_image(self, title: str, context: str, article_title: str = "") -> str:
            safe = title.replace(" ", "_")
            return (
                '<section style="text-align:center;margin:12px 0;">'
                f'<img src="generated://{safe}" style="max-width:100%;border-radius:8px;" />'
                "</section>"
            )

        pipeline._fetch_page_assets = MethodType(fake_fetch_page_assets, pipeline)
        pipeline._generate_cover = MethodType(fake_generate_cover, pipeline)
        pipeline._download_and_upload_image = MethodType(fake_download_and_upload_image, pipeline)
        pipeline._download_and_render_video = MethodType(fake_download_and_render_video, pipeline)
        pipeline._generate_section_image = MethodType(fake_generate_section_image, pipeline)

        success = pipeline.run()

        today = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
        article_path = workdir / "output" / "articles" / f"daily_{today}.html"
        html = article_path.read_text(encoding="utf-8") if article_path.exists() else ""
        title_match = re.search(r"<!--\s*ARTICLE_TITLE:\s*(.*?)\s*-->", html, flags=re.S)
        thumb_match = re.search(r"<!--\s*THUMB_MEDIA_ID:\s*(.*?)\s*-->", html, flags=re.S)

        return SmokeResult(
            success=success,
            workdir=str(workdir),
            article_path=str(article_path),
            html=html,
            llm_generate_calls=len(llm.generate_calls),
            tts_calls=len(tts.calls),
            publish_calls=len(publisher.publish_calls),
            inserted_images=html.count("<img "),
            inserted_videos=html.count("<video "),
            title=title_match.group(1).strip() if title_match else "",
            thumb_media_id=thumb_match.group(1).strip() if thumb_match else "",
            audio_paths=publisher.publish_calls[0]["audio_paths"] if publisher.publish_calls else [],
        )
    finally:
        os.chdir(old_cwd)


def smoke_result_json(workdir: str | Path) -> str:
    return json.dumps(run_smoke_pipeline(workdir).to_dict(), ensure_ascii=False, indent=2)
