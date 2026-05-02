# src/video/segmenter.py
import json
import re
from bs4 import BeautifulSoup
from loguru import logger

from src.llm.client import LLMClient
from src.llm.prompts import load_prompt
from src.video.models import VideoSegment, SegmentType


class Segmenter:
    """LLM智能段落拆分器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def segment(self, article_html: str) -> list[VideoSegment]:
        """拆分文章为视频段落"""
        # 1. 提取标题和纯文本
        title = self._extract_title(article_html)
        text_content = self._extract_text(article_html)

        # 2. 调用LLM拆分
        try:
            segments = self._llm_segment(title, text_content)
            if segments:
                return segments
        except Exception as e:
            logger.warning(f"LLM segmentation failed: {e}, using fallback")

        # 3. 降级方案：按自然段拆分
        return self._fallback_segment(text_content)

    def _extract_title(self, html: str) -> str:
        """从HTML注释或h1标签提取标题"""
        # 尝试从注释提取
        match = re.search(r"<!--\s*ARTICLE_TITLE:\s*(.+?)\s*-->", html)
        if match:
            return match.group(1).strip()
        # 尝试从h1提取
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1:
            return h1.get_text().strip()
        return "未命名文章"

    def _extract_text(self, html: str) -> str:
        """提取HTML中的纯文本内容"""
        soup = BeautifulSoup(html, "html.parser")
        # 移除脚本和样式
        for tag in soup(["script", "style"]):
            tag.decompose()
        # 获取文本
        text = soup.get_text(separator="\n")
        # 清理多余空白
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    def _llm_segment(self, title: str, content: str) -> list[VideoSegment] | None:
        """调用LLM进行智能拆分"""
        prompt_template = load_prompt("video_segment")
        user_prompt = prompt_template.replace("{{title}}", title).replace("{{content}}", content)

        system_prompt = "你是一位视频内容策划专家，擅长将文章拆分成适合视频呈现的段落。"
        response = self.llm.generate(system_prompt, user_prompt)

        # 解析JSON响应
        json_str = self._extract_json(response)
        if not json_str:
            return None

        data = json.loads(json_str)
        segments = []
        for i, item in enumerate(data.get("segments", [])):
            seg_type = SegmentType.WITH_IMAGE if item.get("type") == "with_image" else SegmentType.TEXT_ONLY
            segments.append(VideoSegment(
                id=i,
                text=item.get("text", ""),
                segment_type=seg_type,
                image_prompt=item.get("image_prompt")
            ))

        return segments

    def _extract_json(self, text: str) -> str | None:
        """从文本中提取JSON内容"""
        # 尝试提取代码块中的JSON
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if match:
            return match.group(1).strip()
        # 尝试直接解析
        if text.strip().startswith("{"):
            return text.strip()
        return None

    def _fallback_segment(self, text: str) -> list[VideoSegment]:
        """降级方案：按自然段拆分，全部标记为配图类型"""
        # 先尝试按双换行拆分
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and len(p.strip()) > 10]

        # 如果没有双换行分隔的段落，尝试按单换行拆分
        if not paragraphs:
            paragraphs = [p.strip() for p in text.split("\n") if p.strip() and len(p.strip()) > 5]

        # 如果还是没有，把整个文本作为一个段落
        if not paragraphs and text.strip():
            paragraphs = [text.strip()]

        segments = []
        for i, para in enumerate(paragraphs):
            # 如果段落太长，按句号拆分
            if len(para) > 100:
                sentences = re.split(r"[。！？]", para)
                for j, sent in enumerate(sentences):
                    if sent.strip() and len(sent.strip()) > 5:
                        segments.append(VideoSegment(
                            id=len(segments),
                            text=sent.strip() + "。",
                            segment_type=SegmentType.WITH_IMAGE,
                            image_prompt="AI technology abstract visualization"
                        ))
            else:
                segments.append(VideoSegment(
                    id=i,
                    text=para,
                    segment_type=SegmentType.WITH_IMAGE,
                    image_prompt="AI technology abstract visualization"
                ))
        return segments
