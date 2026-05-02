---
name: 视频制作Pipeline设计
description: 为公众号文章自动生成讲解视频的设计文档
type: project
---

# 视频制作Pipeline设计文档

## 概述

开发一个视频制作pipeline，针对 `output/articles/` 中已有的文章，自动生成对应的讲解视频。视频以PPT+配音形式呈现，通过Codex生成配图、TTS生成配音和字幕，最终使用FFmpeg合成视频。

## 目标平台

微信公众号视频

## 核心需求

1. **LLM智能拆分** - 根据文章内容语义，自动判断最佳拆分点
2. **优先配图** - 尽量为每个段落生成配图，只有无法生成时才退化为纯文字页
3. **动态字幕** - 字幕逐字/逐行出现，配合配音节奏
4. **FFmpeg合成** - 使用FFmpeg命令行进行视频合成
5. **自动触发** - 主pipeline运行时自动为最新文章生成视频

## 架构设计

### 目录结构

```
src/video/
├── __init__.py
├── pipeline.py        # 主流程编排，入口类 VideoPipeline
├── segmenter.py       # LLM智能拆分段落，输出 VideoSegment 列表
├── material.py        # 素材生成器，负责图片和音频生成
├── composer.py        # FFmpeg视频合成，处理字幕、转场、最终输出
└── models.py          # 数据模型定义

prompts/
└── video_segment.md   # LLM拆分提示词模板

tests/
├── test_video_segmenter.py
├── test_video_material.py
├── test_video_composer.py
└── test_video_pipeline.py
```

### 数据流

```
文章HTML → Segmenter → List[VideoSegment] → MaterialGenerator → 素材文件 → Composer → 最终视频
```

### 与主pipeline集成

- 在 `src/pipeline.py` 的 `run()` 方法末尾，检测到新文章生成后自动调用 `VideoPipeline.generate()`
- 通过环境变量 `ENABLE_VIDEO_GENERATION=1` 控制是否启用

## 数据模型

### SegmentType（枚举）

```python
class SegmentType(Enum):
    TEXT_ONLY = "text_only"      # 纯文字页
    WITH_IMAGE = "with_image"    # 配图段落
```

### VideoSegment

```python
@dataclass
class VideoSegment:
    id: int
    text: str                    # 段落文本内容
    segment_type: SegmentType    # 段落类型
    image_prompt: str | None     # 图片生成提示词（LLM生成）
    duration: float | None = None  # 音频时长（秒），素材生成后填充
```

### VideoMaterial

```python
@dataclass
class VideoMaterial:
    segment_id: int
    audio_path: Path             # TTS生成的音频
    image_path: Path | None      # 生成的配图（纯文字页为None）
    subtitle_srt: Path           # 字幕SRT文件
```

### VideoConfig

```python
@dataclass
class VideoConfig:
    output_dir: Path = Path("output/videos")
    video_width: int = 1280
    video_height: int = 720
    fps: int = 30
    subtitle_font: str = "NotoSansSC-Regular.ttf"
    subtitle_fontsize: int = 36
    subtitle_color: str = "white"
    subtitle_bg: str = "black@0.5"
```

## 模块设计

### Segmenter（段落拆分器）

**职责：**
- 解析文章HTML，提取文本内容
- 调用LLM智能拆分段落，判断每段类型（纯文字/配图）
- 为配图段落生成图片提示词

**LLM Prompt设计要点：**
- 输入：文章标题 + 全文内容
- 输出：JSON格式的段落列表，每个段落包含 `text`, `type`, `image_prompt`
- 约束：段落时长控制在5-15秒，优先配图类型

**关键方法：**
```python
class Segmenter:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def segment(self, article_html: str) -> list[VideoSegment]:
        """拆分文章为视频段落"""
```

### MaterialGenerator（素材生成器）

**职责：**
- 为每个段落生成TTS音频
- 为配图段落调用Codex生成图片
- 生成SRT字幕文件

**字幕生成逻辑：**
- 根据音频时长和文本长度，计算每个字的平均显示时间
- 动态字幕效果：每行字幕显示约3-5个字，逐行切换
- 输出标准SRT格式文件

**关键方法：**
```python
class MaterialGenerator:
    def __init__(self, tts_engine: TTSEngine, image_generator: ImageGenerator):
        self.tts = tts_engine
        self.image_gen = image_generator

    def generate(self, segments: list[VideoSegment], output_dir: Path) -> list[VideoMaterial]:
        """为所有段落生成素材"""

    def _generate_audio(self, segment: VideoSegment, output_dir: Path) -> Path:
        """调用TTS生成音频"""

    def _generate_image(self, segment: VideoSegment, output_dir: Path) -> Path:
        """调用Codex生成配图"""

    def _generate_subtitle(self, segment: VideoSegment, audio_path: Path, output_dir: Path) -> Path:
        """根据音频时长生成SRT字幕文件"""
```

### Composer（视频合成器）

**职责：**
- 调用FFmpeg将图片/纯文字背景、音频、字幕合成为视频片段
- 将所有片段拼接成完整视频
- 处理动态字幕效果

**FFmpeg命令设计：**

1. 纯文字页：生成纯色背景 + 居中文字
2. 配图段落：图片 + 音频 + 字幕
3. 动态字幕：使用ASS滤镜实现逐字显示效果
4. 片段拼接：使用concat协议

**关键方法：**
```python
class Composer:
    def __init__(self, config: VideoConfig):
        self.config = config

    def compose(self, materials: list[VideoMaterial], segments: list[VideoSegment], output_path: Path) -> Path:
        """合成最终视频"""

    def _create_text_clip(self, material: VideoMaterial, segment: VideoSegment) -> Path:
        """创建纯文字视频片段"""

    def _create_image_clip(self, material: VideoMaterial, segment: VideoSegment) -> Path:
        """创建配图视频片段"""

    def _concat_clips(self, clip_paths: list[Path], output_path: Path) -> Path:
        """拼接视频片段"""
```

### VideoPipeline（主流程编排）

**职责：**
- 协调Segmenter、MaterialGenerator、Composer完成视频生成
- 与主pipeline集成
- 处理错误和日志

**关键方法：**
```python
class VideoPipeline:
    def __init__(self, config: VideoConfig, llm_client: LLMClient,
                 tts_engine: TTSEngine, image_generator: ImageGenerator):
        self.config = config
        self.segmenter = Segmenter(llm_client)
        self.material_gen = MaterialGenerator(tts_engine, image_generator)
        self.composer = Composer(config)

    def generate(self, article_path: Path) -> Path | None:
        """为文章生成视频，返回视频路径或None（失败时）"""
```

## 错误处理

### LLM拆分失败
- 返回格式不正确 → 重试一次，使用更明确的JSON格式要求
- 超时 → 使用备用方案：按自然段拆分，全部标记为配图类型

### 图片生成失败
- Codex调用超时/失败 → 降级为纯文字页，记录日志

### TTS生成失败
- 单段落失败 → 跳过该段落，继续生成其他段落
- 多段落失败（超过50%）→ 终止整个视频生成

### FFmpeg合成失败
- 单片段合成失败 → 跳过该片段
- 拼接失败 → 保留已生成的片段文件，便于手动恢复

### 磁盘空间不足
- 素材生成前检查剩余空间（需要至少500MB）
- 生成完成后自动清理临时素材文件

### 日志规范
- 每个阶段开始/完成都记录INFO日志
- 失败降级记录WARNING日志
- 致命错误记录ERROR日志并返回None

## 测试策略

### 单元测试
- `test_video_segmenter.py` - 测试HTML解析、LLM调用mock、JSON解析
- `test_video_material.py` - 测试TTS调用mock、图片生成mock、SRT生成逻辑
- `test_video_composer.py` - 测试FFmpeg命令构建、参数正确性

### 集成测试
- `test_video_pipeline.py` - 使用mock组件测试完整流程
- 使用短文本文章测试端到端生成（不超过3个段落）

### 手动验证
- 生成一个完整视频后，手动检查：
  - 视频能否正常播放
  - 字幕是否同步
  - 动态字幕效果是否正确
  - 音频与画面是否匹配

### 测试数据
- 使用 `output/articles/` 中已有的文章作为测试输入
- 测试输出存放在 `output/videos_test/` 避免污染正式目录

## 配置

通过环境变量控制：
- `ENABLE_VIDEO_GENERATION=1` - 启用视频生成功能

## 输出

- 视频文件：`output/videos/{article_name}.mp4`
- 临时素材：`output/videos/{article_name}/` （生成完成后可选择清理）
