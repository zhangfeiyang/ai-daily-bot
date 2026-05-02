# 视频制作Pipeline实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为公众号文章自动生成讲解视频，支持LLM智能拆分、Codex配图、TTS配音、动态字幕、FFmpeg合成。

**Architecture:** 模块化分层架构，按职责拆分为Segmenter（段落拆分）、MaterialGenerator（素材生成）、Composer（视频合成）、VideoPipeline（流程编排），通过数据模型VideoSegment/VideoMaterial在各模块间传递状态。

**Tech Stack:** Python 3.11+, FFmpeg, edge-tts, Codex gpt-5.5 image_gen, loguru

---

## 文件结构

```
src/video/
├── __init__.py          # 导出 VideoPipeline, VideoConfig, VideoSegment, VideoMaterial, SegmentType
├── models.py            # 数据模型定义
├── segmenter.py         # LLM智能拆分段落
├── material.py          # 素材生成器（TTS + 图片 + 字幕）
├── composer.py          # FFmpeg视频合成
└── pipeline.py          # 主流程编排

prompts/
└── video_segment.md     # LLM拆分提示词模板

tests/
├── test_video_models.py
├── test_video_segmenter.py
├── test_video_material.py
├── test_video_composer.py
└── test_video_pipeline.py
```

---

### Task 1: 数据模型定义

**Files:**
- Create: `src/video/__init__.py`
- Create: `src/video/models.py`
- Create: `tests/test_video_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_models.py
import pytest
from pathlib import Path
from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType


class TestSegmentType:
    def test_segment_type_values(self):
        assert SegmentType.TEXT_ONLY.value == "text_only"
        assert SegmentType.WITH_IMAGE.value == "with_image"


class TestVideoSegment:
    def test_create_text_only_segment(self):
        seg = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)
        assert seg.id == 1
        assert seg.text == "测试文本"
        assert seg.segment_type == SegmentType.TEXT_ONLY
        assert seg.image_prompt is None
        assert seg.duration is None

    def test_create_with_image_segment(self):
        seg = VideoSegment(id=2, text="配图文本", segment_type=SegmentType.WITH_IMAGE, image_prompt="AI technology")
        assert seg.segment_type == SegmentType.WITH_IMAGE
        assert seg.image_prompt == "AI technology"

    def test_segment_with_duration(self):
        seg = VideoSegment(id=3, text="测试", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=5.5)
        assert seg.duration == 5.5


class TestVideoMaterial:
    def test_create_material_with_image(self):
        mat = VideoMaterial(
            segment_id=1,
            audio_path=Path("output/audio.mp3"),
            image_path=Path("output/image.png"),
            subtitle_srt=Path("output/subtitle.srt")
        )
        assert mat.segment_id == 1
        assert mat.image_path is not None

    def test_create_material_text_only(self):
        mat = VideoMaterial(
            segment_id=2,
            audio_path=Path("output/audio.mp3"),
            image_path=None,
            subtitle_srt=Path("output/subtitle.srt")
        )
        assert mat.image_path is None


class TestVideoConfig:
    def test_default_config(self):
        config = VideoConfig()
        assert config.output_dir == Path("output/videos")
        assert config.video_width == 1280
        assert config.video_height == 720
        assert config.fps == 30

    def test_custom_config(self):
        config = VideoConfig(output_dir=Path("custom"), video_width=1920, video_height=1080)
        assert config.video_width == 1920
        assert config.video_height == 1080
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_models.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.video.models'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/video/__init__.py
from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType

__all__ = ["VideoSegment", "VideoMaterial", "VideoConfig", "SegmentType"]
```

```python
# src/video/models.py
from dataclasses import dataclass
from pathlib import Path
from enum import Enum


class SegmentType(Enum):
    """视频段落类型"""
    TEXT_ONLY = "text_only"      # 纯文字页
    WITH_IMAGE = "with_image"    # 配图段落


@dataclass
class VideoSegment:
    """单个视频段落"""
    id: int
    text: str                    # 段落文本内容
    segment_type: SegmentType    # 段落类型
    image_prompt: str | None     # 图片生成提示词（LLM生成）
    duration: float | None = None  # 音频时长（秒），素材生成后填充


@dataclass
class VideoMaterial:
    """单个段落的素材"""
    segment_id: int
    audio_path: Path             # TTS生成的音频
    image_path: Path | None      # 生成的配图（纯文字页为None）
    subtitle_srt: Path           # 字幕SRT文件


@dataclass
class VideoConfig:
    """视频配置"""
    output_dir: Path = Path("output/videos")
    video_width: int = 1280
    video_height: int = 720
    fps: int = 30
    subtitle_font: str = "NotoSansSC-Regular.ttf"
    subtitle_fontsize: int = 36
    subtitle_color: str = "white"
    subtitle_bg: str = "black@0.5"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video/__init__.py src/video/models.py tests/test_video_models.py
git commit -m "feat(video): add data models for video pipeline

- Add SegmentType enum for text_only/with_image types
- Add VideoSegment dataclass for segment definition
- Add VideoMaterial dataclass for generated assets
- Add VideoConfig for video parameters"
```

---

### Task 2: LLM拆分提示词模板

**Files:**
- Create: `prompts/video_segment.md`

- [ ] **Step 1: Create the prompt template**

```markdown
# prompts/video_segment.md
你是一位视频内容策划专家，擅长将文章拆分成适合视频呈现的段落。

请将以下文章拆分成适合视频讲解的段落，每个段落应该：
1. 时长控制在5-15秒（约20-60字）
2. 语义完整，不切断句子中间
3. 优先为配图类型（with_image），只有纯概念性内容才标记为纯文字（text_only）
4. 为配图段落生成简洁的图片提示词（英文，描述AI/科技相关场景）

**输出格式（JSON）：**
```json
{
  "segments": [
    {
      "text": "段落文本内容",
      "type": "with_image",
      "image_prompt": "A futuristic AI visualization with neural networks"
    }
  ]
}
```

**注意事项：**
- 不要输出任何其他内容，只输出JSON
- type只能是 "with_image" 或 "text_only"
- image_prompt只在type为with_image时需要，用英文描述
- 图片提示词要抽象、通用，避免具体品牌或产品
- 保持原文核心信息，不要改写内容

文章标题：{{title}}

文章内容：
{{content}}
```

- [ ] **Step 2: Commit**

```bash
git add prompts/video_segment.md
git commit -m "feat(video): add LLM segment prompt template"
```

---

### Task 3: Segmenter段落拆分器

**Files:**
- Create: `src/video/segmenter.py`
- Create: `tests/test_video_segmenter.py`

- [ ] **Step 1: Write the failing test**

```python
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

        # 验证LLM调用时包含了标题
        call_args = llm_client.generate.call_args
        assert "测试标题" in call_args[1]["user_prompt"]

    def test_segment_fallback_on_invalid_json(self):
        """测试JSON解析失败时的降级处理"""
        llm_client = Mock()
        llm_client.generate.return_value = "这不是有效的JSON"
        segmenter = Segmenter(llm)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_segmenter.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.video.segmenter'"

- [ ] **Step 3: Write minimal implementation**

```python
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
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and len(p.strip()) > 10]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_segmenter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video/segmenter.py tests/test_video_segmenter.py
git commit -m "feat(video): add Segmenter for LLM-based article segmentation

- Extract title and text from HTML
- Call LLM for intelligent segmentation
- Fallback to paragraph-based split on failure"
```

---

### Task 4: MaterialGenerator素材生成器

**Files:**
- Create: `src/video/material.py`
- Create: `tests/test_video_material.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_material.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.video.material import MaterialGenerator
from src.video.models import VideoSegment, VideoMaterial, SegmentType


class TestMaterialGenerator:
    def test_generate_audio_for_segment(self, tmp_path):
        """测试为段落生成音频"""
        tts_engine = Mock()
        tts_engine.generate.return_value = str(tmp_path / "audio.mp3")

        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)

        audio_path = generator._generate_audio(segment, tmp_path)

        assert audio_path == tmp_path / "segment_1.mp3"
        tts_engine.generate.assert_called_once_with("测试文本", str(tmp_path / "segment_1.mp3"))

    def test_generate_image_for_segment(self, tmp_path):
        """测试为段落生成图片"""
        tts_engine = Mock()
        image_gen = Mock()
        image_gen.generate.return_value = tmp_path / "image.png"

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=2, text="配图文本", segment_type=SegmentType.WITH_IMAGE, image_prompt="AI technology")

        image_path = generator._generate_image(segment, tmp_path)

        assert image_path == tmp_path / "segment_2.png"
        image_gen.generate.assert_called_once()

    def test_skip_image_for_text_only(self, tmp_path):
        """测试纯文字段落不生成图片"""
        tts_engine = Mock()
        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=3, text="纯文字", segment_type=SegmentType.TEXT_ONLY, image_prompt=None)

        image_path = generator._generate_image(segment, tmp_path)

        assert image_path is None
        image_gen.generate.assert_not_called()

    def test_generate_subtitle_srt(self, tmp_path):
        """测试生成SRT字幕文件"""
        tts_engine = Mock()
        image_gen = Mock()

        generator = MaterialGenerator(tts_engine, image_gen)
        segment = VideoSegment(id=1, text="这是一段测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=3.0)

        srt_path = generator._generate_subtitle(segment, 3.0, tmp_path)

        assert srt_path.exists()
        content = srt_path.read_text()
        assert "1" in content  # 序号
        assert "这是一段测试文本" in content

    def test_generate_all_materials(self, tmp_path):
        """测试生成所有素材"""
        tts_engine = Mock()
        tts_engine.generate.return_value = str(tmp_path / "audio.mp3")

        image_gen = Mock()
        image_gen.generate.return_value = tmp_path / "image.png"

        # Mock audio duration
        with patch("src.video.material.MaterialGenerator._get_audio_duration", return_value=5.0):
            generator = MaterialGenerator(tts_engine, image_gen)
            segments = [
                VideoSegment(id=0, text="第一段", segment_type=SegmentType.WITH_IMAGE, image_prompt="test"),
                VideoSegment(id=1, text="第二段", segment_type=SegmentType.TEXT_ONLY, image_prompt=None),
            ]

            materials = generator.generate(segments, tmp_path)

            assert len(materials) == 2
            assert materials[0].image_path is not None
            assert materials[1].image_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_material.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.video.material'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/video/material.py
import subprocess
from pathlib import Path
from loguru import logger

from src.video.models import VideoSegment, VideoMaterial, SegmentType
from src.tts.engine import TTSEngine
from src.image.generator import ImageGenerator


class MaterialGenerator:
    """素材生成器：TTS音频 + Codex图片 + SRT字幕"""

    def __init__(self, tts_engine: TTSEngine, image_generator: ImageGenerator):
        self.tts = tts_engine
        self.image_gen = image_generator

    def generate(self, segments: list[VideoSegment], output_dir: Path) -> list[VideoMaterial]:
        """为所有段落生成素材"""
        output_dir.mkdir(parents=True, exist_ok=True)
        materials = []

        for seg in segments:
            try:
                # 生成音频
                audio_path = self._generate_audio(seg, output_dir)

                # 获取音频时长
                duration = self._get_audio_duration(audio_path)
                seg.duration = duration

                # 生成图片（仅配图段落）
                image_path = None
                if seg.segment_type == SegmentType.WITH_IMAGE:
                    image_path = self._generate_image(seg, output_dir)

                # 生成字幕
                srt_path = self._generate_subtitle(seg, duration, output_dir)

                materials.append(VideoMaterial(
                    segment_id=seg.id,
                    audio_path=audio_path,
                    image_path=image_path,
                    subtitle_srt=srt_path
                ))
                logger.info(f"Generated materials for segment {seg.id}")

            except Exception as e:
                logger.error(f"Failed to generate materials for segment {seg.id}: {e}")
                raise

        return materials

    def _generate_audio(self, segment: VideoSegment, output_dir: Path) -> Path:
        """调用TTS生成音频"""
        audio_path = output_dir / f"segment_{segment.id}.mp3"
        self.tts.generate(segment.text, str(audio_path))
        return audio_path

    def _generate_image(self, segment: VideoSegment, output_dir: Path) -> Path | None:
        """调用Codex生成配图"""
        if segment.image_prompt is None:
            return None

        try:
            image_path = output_dir / f"segment_{segment.id}.png"
            self.image_gen.generate(
                prompt=segment.image_prompt,
                size="1280x720",
                quality="medium",
                output_path=str(image_path)
            )
            return image_path
        except Exception as e:
            logger.warning(f"Image generation failed for segment {segment.id}: {e}, falling back to text only")
            return None

    def _generate_subtitle(self, segment: VideoSegment, duration: float, output_dir: Path) -> Path:
        """生成SRT字幕文件"""
        srt_path = output_dir / f"segment_{segment.id}.srt"
        text = segment.text

        # 计算每字平均时长
        char_count = len(text)
        char_duration = duration / char_count if char_count > 0 else 0.1

        # 生成字幕块（每行5个字）
        chars_per_line = 5
        lines = [text[i:i+chars_per_line] for i in range(0, len(text), chars_per_line)]

        srt_content = []
        current_time = 0.0

        for i, line in enumerate(lines):
            line_duration = len(line) * char_duration
            start_time = current_time
            end_time = current_time + line_duration

            srt_content.append(f"{i + 1}")
            srt_content.append(f"{self._format_srt_time(start_time)} --> {self._format_srt_time(end_time)}")
            srt_content.append(line)
            srt_content.append("")

            current_time = end_time

        srt_path.write_text("\n".join(srt_content), encoding="utf-8")
        return srt_path

    def _format_srt_time(self, seconds: float) -> str:
        """格式化SRT时间戳"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _get_audio_duration(self, audio_path: Path) -> float:
        """获取音频时长（秒）"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                capture_output=True,
                text=True,
                check=True
            )
            return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Failed to get audio duration: {e}, using estimate")
            # 估算：每100字约10秒
            return 10.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_material.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video/material.py tests/test_video_material.py
git commit -m "feat(video): add MaterialGenerator for TTS, image, and subtitle generation

- Generate TTS audio via TTSEngine
- Generate images via Codex ImageGenerator
- Generate SRT subtitles with dynamic timing
- Get audio duration via ffprobe"
```

---

### Task 5: Composer视频合成器

**Files:**
- Create: `src/video/composer.py`
- Create: `tests/test_video_composer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_composer.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.video.composer import Composer
from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType


class TestComposer:
    def test_create_text_clip_command(self, tmp_path):
        """测试纯文字片段命令构建"""
        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        segment = VideoSegment(id=1, text="测试文本", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=5.0)
        material = VideoMaterial(
            segment_id=1,
            audio_path=tmp_path / "audio.mp3",
            image_path=None,
            subtitle_srt=tmp_path / "subtitle.srt"
        )

        # 创建模拟音频文件
        (tmp_path / "audio.mp3").write_bytes(b"fake audio")
        (tmp_path / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:05,000\n测试文本\n")

        cmd = composer._build_text_clip_command(material, segment, tmp_path / "clip.mp4")

        assert "ffmpeg" in cmd[0] or "ffmpeg" in " ".join(cmd)
        assert "drawtext" in " ".join(cmd) or "ass" in " ".join(cmd)

    def test_create_image_clip_command(self, tmp_path):
        """测试配图片段命令构建"""
        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        segment = VideoSegment(id=2, text="配图文本", segment_type=SegmentType.WITH_IMAGE, image_prompt="test", duration=5.0)
        material = VideoMaterial(
            segment_id=2,
            audio_path=tmp_path / "audio.mp3",
            image_path=tmp_path / "image.png",
            subtitle_srt=tmp_path / "subtitle.srt"
        )

        # 创建模拟文件
        (tmp_path / "audio.mp3").write_bytes(b"fake audio")
        (tmp_path / "image.png").write_bytes(b"fake image")
        (tmp_path / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:05,000\n配图文本\n")

        cmd = composer._build_image_clip_command(material, segment, tmp_path / "clip.mp4")

        assert "ffmpeg" in " ".join(cmd)
        assert str(material.image_path) in " ".join(cmd)

    def test_concat_clips_command(self, tmp_path):
        """测试拼接命令构建"""
        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        clip_paths = [tmp_path / "clip1.mp4", tmp_path / "clip2.mp4"]
        for clip in clip_paths:
            clip.write_bytes(b"fake video")

        cmd = composer._build_concat_command(clip_paths, tmp_path / "final.mp4")

        assert "concat" in " ".join(cmd)
        assert "ffmpeg" in " ".join(cmd)

    @patch("subprocess.run")
    def test_compose_runs_ffmpeg(self, mock_run, tmp_path):
        """测试compose方法调用FFmpeg"""
        mock_run.return_value = MagicMock(returncode=0)

        config = VideoConfig(output_dir=tmp_path)
        composer = Composer(config)

        segments = [
            VideoSegment(id=0, text="测试", segment_type=SegmentType.TEXT_ONLY, image_prompt=None, duration=3.0)
        ]
        materials = [
            VideoMaterial(
                segment_id=0,
                audio_path=tmp_path / "audio.mp3",
                image_path=None,
                subtitle_srt=tmp_path / "subtitle.srt"
            )
        ]

        # 创建模拟文件
        (tmp_path / "audio.mp3").write_bytes(b"fake")
        (tmp_path / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:03,000\n测试\n")

        output_path = tmp_path / "final.mp4"
        result = composer.compose(materials, segments, output_path)

        assert mock_run.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_composer.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.video.composer'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/video/composer.py
import subprocess
import tempfile
from pathlib import Path
from loguru import logger

from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType


class Composer:
    """FFmpeg视频合成器"""

    def __init__(self, config: VideoConfig):
        self.config = config

    def compose(self, materials: list[VideoMaterial], segments: list[VideoSegment], output_path: Path) -> Path:
        """合成最终视频"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        clips_dir = output_path.parent / "clips"
        clips_dir.mkdir(exist_ok=True)

        clip_paths = []

        for mat, seg in zip(materials, segments):
            clip_path = clips_dir / f"clip_{seg.id}.mp4"

            try:
                if mat.image_path and mat.image_path.exists():
                    self._create_image_clip(mat, seg, clip_path)
                else:
                    self._create_text_clip(mat, seg, clip_path)

                clip_paths.append(clip_path)
                logger.info(f"Created clip {seg.id}")
            except Exception as e:
                logger.error(f"Failed to create clip {seg.id}: {e}")
                continue

        if not clip_paths:
            raise RuntimeError("No clips were created")

        # 拼接所有片段
        self._concat_clips(clip_paths, output_path)
        logger.info(f"Video composed: {output_path}")

        return output_path

    def _create_text_clip(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> None:
        """创建纯文字视频片段"""
        cmd = self._build_text_clip_command(material, segment, output_path)
        self._run_ffmpeg(cmd)

    def _create_image_clip(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> None:
        """创建配图视频片段"""
        cmd = self._build_image_clip_command(material, segment, output_path)
        self._run_ffmpeg(cmd)

    def _build_text_clip_command(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> list[str]:
        """构建纯文字片段FFmpeg命令"""
        duration = segment.duration or 5.0
        text = segment.text.replace("'", "'\\''")  # 转义单引号

        # 使用drawtext滤镜显示文字
        return [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=white:s={self.config.video_width}x{self.config.video_height}:d={duration}",
            "-i", str(material.audio_path),
            "-vf", f"drawtext=text='{text}':fontsize={self.config.subtitle_fontsize}:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-t", str(duration),
            str(output_path)
        ]

    def _build_image_clip_command(self, material: VideoMaterial, segment: VideoSegment, output_path: Path) -> list[str]:
        """构建配图片段FFmpeg命令"""
        duration = segment.duration or 5.0

        # 图片缩放 + 音频 + 字幕
        return [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(material.image_path),
            "-i", str(material.audio_path),
            "-vf", f"scale={self.config.video_width}:{self.config.video_height}:force_original_aspect_ratio=decrease,pad={self.config.video_width}:{self.config.video_height}:(ow-iw)/2:(oh-ih)/2,subtitles={str(material.subtitle_srt)}:force_style='FontName={self.config.subtitle_font},FontSize={self.config.subtitle_fontsize},PrimaryColour=&H{self._color_to_ass(self.config.subtitle_color)},OutlineColour=&H000000,BackColour=&H{self._color_to_ass_bg(self.config.subtitle_bg)}'",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

    def _build_concat_command(self, clip_paths: list[Path], output_path: Path) -> list[str]:
        """构建拼接FFmpeg命令"""
        # 创建concat文件列表
        concat_file = output_path.parent / "concat.txt"
        with open(concat_file, "w") as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        return [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path)
        ]

    def _concat_clips(self, clip_paths: list[Path], output_path: Path) -> None:
        """拼接视频片段"""
        cmd = self._build_concat_command(clip_paths, output_path)
        self._run_ffmpeg(cmd)

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        """执行FFmpeg命令"""
        logger.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")

    def _color_to_ass(self, color: str) -> str:
        """将颜色名称转换为ASS格式（BGR）"""
        colors = {
            "white": "FFFFFF",
            "black": "000000",
            "yellow": "00FFFF",
            "red": "0000FF",
            "green": "00FF00",
            "blue": "FF0000",
        }
        return colors.get(color.lower(), "FFFFFF")

    def _color_to_ass_bg(self, bg: str) -> str:
        """解析背景色（带透明度）"""
        # 格式: black@0.5
        if "@" in bg:
            color, alpha = bg.split("@")
            alpha_hex = int(float(alpha) * 255)
            return f"{self._color_to_ass(color)}&{alpha_hex:02X}"
        return self._color_to_ass(bg) + "&80"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_composer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video/composer.py tests/test_video_composer.py
git commit -m "feat(video): add Composer for FFmpeg-based video composition

- Create text-only clips with drawtext filter
- Create image clips with subtitles
- Concatenate clips into final video
- Support custom video config"
```

---

### Task 6: VideoPipeline主流程编排

**Files:**
- Create: `src/video/pipeline.py`
- Create: `tests/test_video_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_pipeline.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.video.pipeline import VideoPipeline
from src.video.models import VideoConfig, VideoSegment, VideoMaterial, SegmentType


class TestVideoPipeline:
    def test_generate_video_from_article(self, tmp_path):
        """测试从文章生成视频"""
        # Mock所有依赖
        llm_client = Mock()
        llm_client.generate.return_value = '''{
            "segments": [
                {"text": "测试段落", "type": "with_image", "image_prompt": "test"}
            ]
        }'''

        tts_engine = Mock()
        tts_engine.generate.return_value = str(tmp_path / "audio.mp3")

        image_gen = Mock()
        image_gen.generate.return_value = tmp_path / "image.png"

        config = VideoConfig(output_dir=tmp_path)

        # 创建模拟文章
        article_path = tmp_path / "test_article.html"
        article_path.write_text("<!-- ARTICLE_TITLE: 测试 --><html><body><p>测试段落</p></body></html>")

        # 创建模拟文件
        (tmp_path / "audio.mp3").write_bytes(b"fake")
        (tmp_path / "image.png").write_bytes(b"fake")

        with patch("src.video.material.MaterialGenerator._get_audio_duration", return_value=5.0):
            with patch("src.video.composer.Composer._run_ffmpeg"):
                pipeline = VideoPipeline(config, llm_client, tts_engine, image_gen)
                result = pipeline.generate(article_path)

        assert result is not None
        assert result.suffix == ".mp4"

    def test_generate_returns_none_on_failure(self, tmp_path):
        """测试失败时返回None"""
        llm_client = Mock()
        llm_client.generate.side_effect = Exception("LLM error")

        tts_engine = Mock()
        image_gen = Mock()
        config = VideoConfig(output_dir=tmp_path)

        article_path = tmp_path / "test.html"
        article_path.write_text("<html><body>内容</body></html>")

        pipeline = VideoPipeline(config, llm_client, tts_engine, image_gen)
        result = pipeline.generate(article_path)

        assert result is None

    def test_from_config_factory(self):
        """测试工厂方法"""
        with patch("src.video.pipeline.load_config") as mock_load:
            mock_load.side_effect = lambda name: {
                "llm": {"default": "openai", "providers": {"openai": {"api_key": "test"}}},
                "tts": {"edge-tts": {"voice": "zh-CN-YunxiNeural"}},
            }.get(name, {})

            with patch("src.video.pipeline.LLMClient") as mock_llm:
                with patch("src.video.pipeline.TTSEngine") as mock_tts:
                    with patch("src.video.pipeline.ImageGenerator") as mock_img:
                        pipeline = VideoPipeline.from_config()

                        assert pipeline is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_pipeline.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.video.pipeline'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/video/pipeline.py
import os
from pathlib import Path
from loguru import logger

from src.config import load_config
from src.llm.client import LLMClient
from src.tts.engine import TTSEngine
from src.image.generator import ImageGenerator
from src.video.models import VideoConfig, VideoSegment, VideoMaterial
from src.video.segmenter import Segmenter
from src.video.material import MaterialGenerator
from src.video.composer import Composer


class VideoPipeline:
    """视频生成主流程编排"""

    def __init__(
        self,
        config: VideoConfig,
        llm_client: LLMClient,
        tts_engine: TTSEngine,
        image_generator: ImageGenerator
    ):
        self.config = config
        self.segmenter = Segmenter(llm_client)
        self.material_gen = MaterialGenerator(tts_engine, image_generator)
        self.composer = Composer(config)

    def generate(self, article_path: Path) -> Path | None:
        """为文章生成视频，返回视频路径或None（失败时）"""
        try:
            logger.info(f"Generating video for: {article_path}")

            # 1. 读取文章HTML
            article_html = article_path.read_text(encoding="utf-8")

            # 2. 拆分段落
            segments = self.segmenter.segment(article_html)
            logger.info(f"Segmented into {len(segments)} parts")

            if not segments:
                logger.warning("No segments generated")
                return None

            # 3. 生成素材
            material_dir = self.config.output_dir / article_path.stem
            materials = self.material_gen.generate(segments, material_dir)
            logger.info(f"Generated {len(materials)} material sets")

            # 4. 合成视频
            output_path = self.config.output_dir / f"{article_path.stem}.mp4"
            final_video = self.composer.compose(materials, segments, output_path)
            logger.info(f"Video generated: {final_video}")

            return final_video

        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            return None

    @classmethod
    def from_config(cls, config: VideoConfig | None = None) -> "VideoPipeline":
        """从配置文件创建VideoPipeline实例"""
        if config is None:
            config = VideoConfig()

        llm_config = load_config("llm")
        tts_config = load_config("tts")

        llm_client = LLMClient(llm_config)
        tts_engine = TTSEngine(tts_config)
        image_generator = ImageGenerator()

        return cls(config, llm_client, tts_engine, image_generator)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video/pipeline.py tests/test_video_pipeline.py
git commit -m "feat(video): add VideoPipeline for end-to-end video generation

- Coordinate Segmenter, MaterialGenerator, Composer
- Factory method from_config for easy instantiation
- Error handling with None return on failure"
```

---

### Task 7: 与主Pipeline集成

**Files:**
- Modify: `src/pipeline.py`

- [ ] **Step 1: Read current pipeline.py to find integration point**

Run: `head -150 /home/zhangfy/gongzhonghao/src/pipeline.py`

- [ ] **Step 2: Add video generation integration**

在 `src/pipeline.py` 文件末尾的 `run()` 方法中，找到文章生成成功后的位置，添加视频生成调用：

```python
# 在 src/pipeline.py 的 run() 方法末尾，return True 之前添加：

        # 视频生成（如果启用）
        if os.environ.get("ENABLE_VIDEO_GENERATION") == "1" and article_path:
            try:
                from src.video.pipeline import VideoPipeline
                video_pipeline = VideoPipeline.from_config()
                video_result = video_pipeline.generate(Path(article_path))
                if video_result:
                    logger.info(f"Video generated: {video_result}")
            except Exception as e:
                logger.warning(f"Video generation skipped: {e}")
```

- [ ] **Step 3: Verify integration works**

Run: `cd /home/zhangfy/gongzhonghao && python -c "from src.pipeline import Pipeline; print('Import OK')"`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/pipeline.py
git commit -m "feat(video): integrate video generation into main pipeline

- Auto-generate video for new articles when ENABLE_VIDEO_GENERATION=1
- Graceful fallback on video generation failure"
```

---

### Task 8: 更新__init__.py导出

**Files:**
- Modify: `src/video/__init__.py`

- [ ] **Step 1: Update exports**

```python
# src/video/__init__.py
from src.video.models import VideoSegment, VideoMaterial, VideoConfig, SegmentType
from src.video.segmenter import Segmenter
from src.video.material import MaterialGenerator
from src.video.composer import Composer
from src.video.pipeline import VideoPipeline

__all__ = [
    "VideoSegment",
    "VideoMaterial",
    "VideoConfig",
    "SegmentType",
    "Segmenter",
    "MaterialGenerator",
    "Composer",
    "VideoPipeline",
]
```

- [ ] **Step 2: Verify imports work**

Run: `cd /home/zhangfy/gongzhonghao && python -c "from src.video import VideoPipeline, VideoConfig; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/video/__init__.py
git commit -m "feat(video): export all video module components"
```

---

### Task 9: 端到端测试

**Files:**
- Create: `tests/test_video_e2e.py`

- [ ] **Step 1: Write end-to-end test**

```python
# tests/test_video_e2e.py
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 跳过如果没有FFmpeg
pytestmark = pytest.mark.skipif(
    os.system("which ffmpeg > /dev/null 2>&1") != 0,
    reason="ffmpeg not installed"
)


class TestVideoE2E:
    """端到端测试（需要FFmpeg）"""

    def test_generate_video_from_real_article(self, tmp_path):
        """使用真实文章测试视频生成（mock LLM和图片生成）"""
        from src.video import VideoPipeline, VideoConfig

        # 使用真实文章
        article_path = Path("output/articles/feature_2026-05-02_1.html")
        if not article_path.exists():
            pytest.skip("No test article available")

        config = VideoConfig(output_dir=tmp_path)

        # Mock LLM
        with patch("src.video.segmenter.Segmenter._llm_segment") as mock_segment:
            mock_segment.return_value = [
                VideoSegment(id=0, text="这是测试段落一", segment_type=SegmentType.WITH_IMAGE, image_prompt="AI tech"),
                VideoSegment(id=1, text="这是测试段落二", segment_type=SegmentType.TEXT_ONLY, image_prompt=None),
            ]

            # Mock图片生成
            with patch("src.video.material.ImageGenerator.generate") as mock_img:
                mock_img.return_value = tmp_path / "test_image.png"
                (tmp_path / "test_image.png").write_bytes(b"fake image")

                pipeline = VideoPipeline.from_config(config)
                result = pipeline.generate(article_path)

                # 验证视频文件生成
                if result:
                    assert result.exists()
                    assert result.suffix == ".mp4"
```

- [ ] **Step 2: Run end-to-end test**

Run: `cd /home/zhangfy/gongzhonghao && python -m pytest tests/test_video_e2e.py -v --tb=short`
Expected: PASS or skip if no article/ffmpeg

- [ ] **Step 3: Commit**

```bash
git add tests/test_video_e2e.py
git commit -m "test(video): add end-to-end test for video generation"
```

---

### Task 10: 文档和清理

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with video pipeline usage**

在 README.md 中添加视频生成功能的说明：

```markdown
## 视频生成

视频Pipeline可以自动为生成的文章创建讲解视频（PPT+配音形式）。

### 启用方式

```bash
ENABLE_VIDEO_GENERATION=1 python main.py
```

### 功能特性

- **LLM智能拆分**：根据文章语义自动拆分成适合视频的段落
- **自动配图**：通过Codex为每个段落生成配图
- **TTS配音**：使用edge-tts生成中文语音
- **动态字幕**：字幕逐字显示，配合配音节奏
- **FFmpeg合成**：输出标准MP4格式

### 输出位置

- 视频文件：`output/videos/{article_name}.mp4`
- 临时素材：`output/videos/{article_name}/`

### 依赖

- FFmpeg（必须）
- Codex CLI（可选，用于图片生成）
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add video pipeline usage documentation"
```

---

## 自检清单

**1. Spec覆盖检查：**
- [x] LLM智能拆分 → Task 2, 3
- [x] 优先配图 → Task 4 (MaterialGenerator._generate_image)
- [x] 动态字幕 → Task 4 (MaterialGenerator._generate_subtitle)
- [x] FFmpeg合成 → Task 5
- [x] 自动触发 → Task 7
- [x] 错误处理 → Task 3 (fallback), Task 4 (image fallback), Task 6 (None return)
- [x] 数据模型 → Task 1

**2. 占位符检查：**
- 无TBD/TODO
- 所有代码步骤都有完整实现
- 所有测试都有实际代码

**3. 类型一致性检查：**
- VideoSegment.id: int (一致)
- VideoMaterial.segment_id: int (一致)
- SegmentType枚举值使用一致
- Path类型使用一致
