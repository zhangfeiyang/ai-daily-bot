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

        # Split text into chunks to avoid edge-tts limits
        max_chars = 5000
        chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars)] if len(text) > max_chars else [text]

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if len(chunks) == 1:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            self._run_async(communicate.save(output_path), loop)
        else:
            # Generate chunks and concatenate
            import tempfile
            chunk_paths = []
            for i, chunk in enumerate(chunks):
                chunk_path = f"{output_path}.part{i}.mp3"
                communicate = edge_tts.Communicate(chunk, self.voice, rate=self.rate)
                self._run_async(communicate.save(chunk_path), loop)
                chunk_paths.append(chunk_path)
            # Concatenate MP3 files
            with open(output_path, "wb") as out:
                for cp in chunk_paths:
                    with open(cp, "rb") as f:
                        out.write(f.read())
                    Path(cp).unlink()

        logger.info(f"TTS audio saved to {output_path}")
        return output_path

    def _run_async(self, coro, loop):
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                future.result()
        else:
            asyncio.run(coro)
