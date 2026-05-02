# tests/test_video_segmenter.py
import pytest
from unittest.mock import Mock, patch
from src.video.segmenter import Segmenter
from src.video.models import VideoSegment, SegmentType


class TestSegmenter:
    def test_segment_simple_article(self):
        """测试简单文章拆分"""
        llm_client = Mock()
        llm_client.generate.return_value = '''```json
{
  "segments": [
    {"text": "这是第一段内容", "type": "with_image", "image_prompt": "AI technology"},
    {"text": "这是第二段内容", "type": "text_only", "image_prompt": null}
  ]
}
```'''
        segmenter = Segmenter(llm_client)
        html = "<html><body><h1>测试文章</h1><p>这是第一段内容。这是第二段内容。</p></body></html>"

        segments = segmenter.segment(html)

        assert len(segments) == 2
        assert segments[0].segment_type == SegmentType.WITH_IMAGE
        assert segments[0].image_prompt == "AI technology"
        assert segments[1].segment_type == SegmentType.TEXT_ONLY

    def test_segment_extracts_title_from_html(self):
        """测试从HTML提取标题"""
        llm_client = Mock()
        llm_client.generate.return_value = '{"segments": []}'
        segmenter = Segmenter(llm_client)

        html = "<!-- ARTICLE_TITLE: 测试标题 --><html><body>内容</body></html>"
        segmenter.segment(html)

        # 验证LLM调用时包含了标题 (call_args.args[1] is user_prompt)
        call_args = llm_client.generate.call_args
        assert "测试标题" in call_args.args[1]

    def test_segment_fallback_on_invalid_json(self):
        """测试JSON解析失败时的降级处理"""
        llm_client = Mock()
        llm_client.generate.return_value = "这不是有效的JSON"
        segmenter = Segmenter(llm_client)

        html = "<!-- ARTICLE_TITLE: 测试 --><html><body><p>第一段。</p><p>第二段。</p></body></html>"
        segments = segmenter.segment(html)

        # 降级方案：按段落拆分，全部为配图类型
        assert len(segments) >= 1
        for seg in segments:
            assert seg.segment_type == SegmentType.WITH_IMAGE

    def test_segment_assigns_sequential_ids(self):
        """测试段落ID按顺序分配"""
        llm_client = Mock()
        llm_client.generate.return_value = '''{
  "segments": [
    {"text": "段落1", "type": "with_image", "image_prompt": "test1"},
    {"text": "段落2", "type": "with_image", "image_prompt": "test2"},
    {"text": "段落3", "type": "with_image", "image_prompt": "test3"}
  ]
}'''
        segmenter = Segmenter(llm_client)
        segments = segmenter.segment("<html><body>内容</body></html>")

        for i, seg in enumerate(segments):
            assert seg.id == i
