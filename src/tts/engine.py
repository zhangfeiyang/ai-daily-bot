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
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, communicate.save(output_path))
                future.result()
        else:
            asyncio.run(communicate.save(output_path))

        logger.info(f"TTS audio saved to {output_path}")
        return output_path
