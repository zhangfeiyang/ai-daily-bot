# src/tts/engine.py
import asyncio
from pathlib import Path
import edge_tts
from loguru import logger

WECHAT_AUDIO_LIMIT = 1900 * 1024  # ~1.9MB 留余量


class TTSEngine:
    def __init__(self, config: dict):
        tts_config = config.get(config.get("default", "edge-tts"), {})
        self.voice = tts_config.get("voice", "zh-CN-YunxiNeural")
        self.rate = tts_config.get("rate", "+0%")
        self.output_format = tts_config.get("output_format", "mp3")

    def generate(self, text: str, output_path: str) -> list[str]:
        """Generate TTS audio. Returns list of audio file paths.

        If the total audio exceeds WeChat's 2MB limit, it is automatically
        split into multiple files each under the limit.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        max_chars = 2000
        chunks = (
            [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
            if len(text) > max_chars
            else [text]
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        # Generate each chunk as a separate temporary file
        chunk_paths: list[str] = []
        for i, chunk in enumerate(chunks):
            chunk_path = f"{output_path}.part{i}.mp3"
            communicate = edge_tts.Communicate(chunk, self.voice, rate=self.rate)
            self._run_async(communicate.save(chunk_path), loop)
            chunk_paths.append(chunk_path)

        # Decide whether we need to split into multiple output files
        total_size = sum(Path(p).stat().st_size for p in chunk_paths)

        if total_size <= WECHAT_AUDIO_LIMIT:
            # Concatenate into single file
            with open(output_path, "wb") as out:
                for cp in chunk_paths:
                    with open(cp, "rb") as f:
                        out.write(f.read())
                    Path(cp).unlink()
            logger.info(f"TTS audio saved to {output_path}")
            return [output_path]

        # Split: accumulate chunks into parts, each ≤ 2MB
        parts: list[str] = []
        part_idx = 0
        part_size = 0
        part_files: list[str] = []

        def flush_part():
            nonlocal part_idx, part_size, part_files
            if not part_files:
                return
            part_path = output_path.replace(".mp3", f"_part{part_idx}.mp3")
            with open(part_path, "wb") as out:
                for pf in part_files:
                    with open(pf, "rb") as f:
                        out.write(f.read())
                    Path(pf).unlink()
            parts.append(part_path)
            logger.info(f"TTS part {part_idx}: {Path(part_path).stat().st_size / 1024:.0f}KB")
            part_idx += 1
            part_size = 0
            part_files = []

        for cp in chunk_paths:
            sz = Path(cp).stat().st_size
            if part_size + sz > WECHAT_AUDIO_LIMIT and part_files:
                flush_part()
            part_files.append(cp)
            part_size += sz

        flush_part()

        logger.info(f"TTS audio split into {len(parts)} parts")
        return parts

    def _run_async(self, coro, loop):
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                future.result()
        else:
            asyncio.run(coro)
