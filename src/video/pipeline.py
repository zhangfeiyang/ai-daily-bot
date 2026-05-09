# src/video/pipeline.py
import json
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

            # 确定素材目录
            material_dir = self.config.output_dir / article_path.stem
            segments_cache = material_dir / "segments.json"

            # 1. 尝试复用已保存的段落划分
            segments = self._load_segments(segments_cache)

            if segments:
                logger.info(f"Reusing {len(segments)} cached segments")
            else:
                # 2. 读取文章HTML并拆分段落
                article_html = article_path.read_text(encoding="utf-8")
                segments = self.segmenter.segment(article_html)
                logger.info(f"Segmented into {len(segments)} parts")

                # 保存段落划分供后续复用
                self._save_segments(segments, segments_cache)

            if not segments:
                logger.warning("No segments generated")
                return None

            # 3. 生成素材（自动复用已存在的素材）
            materials = self.material_gen.generate(segments, material_dir)
            logger.info(f"Materials ready for {len(materials)} segments")

            # 4. 合成视频
            output_path = self.config.output_dir / f"{article_path.stem}.mp4"
            final_video = self.composer.compose(materials, segments, output_path)
            logger.info(f"Video generated: {final_video}")

            return final_video

        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            return None

    def _load_segments(self, cache_path: Path) -> list[VideoSegment] | None:
        """从缓存加载段落划分"""
        if not cache_path.exists():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            from src.video.models import SegmentType
            return [
                VideoSegment(
                    id=item["id"],
                    text=item["text"],
                    segment_type=SegmentType(item["segment_type"]),
                    image_prompt=item.get("image_prompt"),
                    duration=item.get("duration")
                )
                for item in data
            ]
        except Exception as e:
            logger.warning(f"Failed to load segments cache: {e}")
            return None

    def _save_segments(self, segments: list[VideoSegment], cache_path: Path) -> None:
        """保存段落划分到缓存"""
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {
                    "id": seg.id,
                    "text": seg.text,
                    "segment_type": seg.segment_type.value,
                    "image_prompt": seg.image_prompt,
                    "duration": seg.duration
                }
                for seg in segments
            ]
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save segments cache: {e}")

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