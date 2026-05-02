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