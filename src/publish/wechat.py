# src/publish/wechat.py
import json
import os
import re
import time
from pathlib import Path

import requests
from loguru import logger


class WeChatPublisher:
    BASE_URL = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, config: dict):
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.timeout = float(config.get("timeout_seconds") or os.environ.get("WECHAT_REQUEST_TIMEOUT_SECONDS", "30"))
        self._token = None
        self._token_expires = 0
        self._default_thumb_media_id = None

    def _get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        return self._refresh_access_token()

    def _refresh_access_token(self) -> str:
        self._token = None
        self._token_expires = 0

        url = f"{self.BASE_URL}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise RuntimeError(f"WeChat API error: {data}")

        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 7200) - 300
        logger.info("WeChat access_token refreshed")
        return self._token

    @staticmethod
    def _is_invalid_token_response(data: dict) -> bool:
        return data.get("errcode") in {40001, 40014, 42001}

    def _post_with_token_retry(self, url: str, *, params: dict, **kwargs):
        """POST once, refresh token on invalid-token responses, then retry once."""
        kwargs.setdefault("timeout", self.timeout)
        resp = requests.post(url, params=params, **kwargs)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            return resp, {}

        if self._is_invalid_token_response(data):
            logger.warning("WeChat access_token invalid during request; refreshing and retrying once")
            token = self._refresh_access_token()
            retry_params = dict(params)
            retry_params["access_token"] = token
            resp = requests.post(url, params=retry_params, **kwargs)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                data = {}
        return resp, data

    def upload_audio(self, audio_path: str) -> str:
        token = self._get_access_token()
        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "voice"}

        with open(audio_path, "rb") as f:
            files = {"media": (Path(audio_path).name, f, "audio/mpeg")}
            resp = requests.post(url, params=params, files=files, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if "media_id" not in data:
            raise RuntimeError(f"WeChat upload audio failed: {data}")

        logger.info(f"Audio uploaded, media_id={data['media_id']}")
        return data["media_id"]

    def upload_thumb(self, image_path: str) -> str:
        token = self._get_access_token()
        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "image"}

        with open(image_path, "rb") as f:
            files = {"media": (Path(image_path).name, f, "image/jpeg")}
            resp = requests.post(url, params=params, files=files, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if "media_id" not in data:
            raise RuntimeError(f"WeChat upload thumb failed: {data}")

        return data["media_id"]

    def publish_article(
        self,
        title: str,
        content: str,
        audio_paths: list[str] | None = None,
        audio_path: str = "",
        thumb_media_id: str = "",
    ) -> str:
        token = self._get_access_token()

        draft_id = self.create_draft(
            title=title,
            content=content,
            audio_paths=audio_paths,
            thumb_media_id=thumb_media_id,
        )

        # Try to publish directly; if unauthorized (subscription account), stop at draft
        pub_url = f"{self.BASE_URL}/freepublish/submit"
        pub_data = {"media_id": draft_id}
        resp = requests.post(pub_url, params={"access_token": token}, json=pub_data, timeout=self.timeout)
        resp.raise_for_status()
        pub = resp.json()

        if pub.get("errcode") == 48001:
            logger.info("freepublish API unauthorized (subscription account). Draft saved, manual publish required.")
            return draft_id

        if "publish_id" not in pub:
            raise RuntimeError(f"WeChat publish failed: {pub}")

        logger.info(f"Article published, publish_id={pub['publish_id']}")
        return pub["publish_id"]

    def create_draft(
        self,
        title: str,
        content: str,
        audio_paths: list[str] | None = None,
        audio_path: str = "",
        thumb_media_id: str = "",
    ) -> str:
        token = self._get_access_token()

        if audio_path and not audio_paths:
            audio_paths = [audio_path]

        # Upload audio parts if provided
        if audio_paths:
            for i, ap in enumerate(audio_paths):
                sz = Path(ap).stat().st_size
                if sz <= 2 * 1024 * 1024:
                    media_id = self.upload_audio(ap)
                    logger.info(f"Audio part {i+1}/{len(audio_paths)} uploaded, media_id={media_id}")
                else:
                    logger.warning(f"Audio part {i+1} still too large ({sz/1024/1024:.1f}MB), skipped")

        body = self._normalize_article_content_for_draft(content)

        # If no thumb provided, upload a default one
        if not thumb_media_id:
            thumb_media_id = self._upload_default_thumb(token)

        draft_url = f"{self.BASE_URL}/draft/add"
        draft_data = {
            "articles": [
                {
                    "title": title,
                    "author": "躺在十字路口",
                    "content": body,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 1,
                }
            ],
        }
        resp, draft = self._post_with_token_retry(
            draft_url,
            params={"access_token": token},
            data=json.dumps(draft_data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        if "media_id" not in draft:
            raise RuntimeError(f"WeChat create draft failed: {draft}")

        logger.info(f"Draft created, media_id={draft['media_id']}")
        return draft["media_id"]

    def _normalize_article_content_for_draft(self, content: str) -> str:
        content = re.sub(r"<!--\s*ARTICLE_TITLE:.*?-->\s*", "", content, flags=re.S)
        content = re.sub(r"<!--\s*THUMB_MEDIA_ID:.*?-->\s*", "", content, flags=re.S)

        # Video pattern (legacy - for any remaining video tags)
        video_pattern = re.compile(
            r'<section style="text-align:center;margin:12px 0;" '
            r'data-original-url="([^"]*)" '
            r'data-section-title="([^"]*)">\s*'
            r'<video src="([^"]+)" controls="controls" style="max-width:100%;border-radius:8px;"></video>\s*'
            r'</section>',
            flags=re.S,
        )

        def replace_video(match: re.Match) -> str:
            original_url = match.group(1)
            section_title = match.group(2) or "视频素材"
            local_path = match.group(3)

            # Try to upload video to WeChat material library
            if local_path and not local_path.startswith("http"):
                media_id = self.upload_video(local_path, section_title)
                if media_id:
                    # Return a video link that references the uploaded media
                    return self._render_video_media_card(media_id, section_title, original_url)

            return self._render_video_link_card(original_url, section_title)

        content = video_pattern.sub(replace_video, content)

        # GIF pattern - upload as image and embed
        gif_pattern = re.compile(
            r'<section style="text-align:center;margin:12px 0;">\s*'
            r'<img src="([^"]+\.gif)" style="max-width:100%;border-radius:8px;" />\s*'
            r'</section>',
            flags=re.S,
        )

        def replace_gif(match: re.Match) -> str:
            gif_path = match.group(1)
            if gif_path and not gif_path.startswith("http"):
                # Upload GIF as image
                try:
                    img_url = self.upload_image(gif_path)
                    if img_url:
                        return (
                            f'<section style="text-align:center;margin:12px 0;">'
                            f'<img src="{img_url}" style="max-width:100%;border-radius:8px;" />'
                            f'</section>'
                        )
                except Exception as e:
                    logger.warning(f"Failed to upload GIF: {e}")
            return match.group(0)  # Return original if upload fails

        content = gif_pattern.sub(replace_gif, content)
        return content

    @staticmethod
    def _render_video_media_card(media_id: str, title: str, original_url: str) -> str:
        """Render a video embed using mpvideo tag for WeChat articles.

        WeChat supports <mpvideo> tag with data-mpvid attribute to embed videos
        from the material library directly into articles.
        """
        safe_title = re.sub(r"<[^>]+>", "", title).strip() or "视频素材"
        return (
            '<section style="margin:12px 0;text-align:center;">'
            f'<mpvideo data-mpvid="{media_id}" name="{safe_title}" style="max-width:100%;"></mpvideo>'
            '</section>'
        )

    @staticmethod
    def _render_video_link_card(video_url: str, title: str) -> str:
        safe_title = re.sub(r"<[^>]+>", "", title).strip() or "视频素材"
        return (
            '<section style="margin:12px 0;padding:12px 14px;border-radius:10px;'
            'background:#f7f8fa;border:1px solid #eceff3;">'
            '<p style="margin:0 0 6px 0;color:#1a1a2e;font-weight:600;">视频素材</p>'
            f'<p style="margin:0;color:#666;font-size:13px;line-height:1.6;">{safe_title} 的原始视频可点开查看：</p>'
            f'<p style="margin:4px 0 0 0;font-size:12px;word-break:break-all;">'
            f'<a href="{video_url}" style="color:#1a73e8;text-decoration:none;">{video_url}</a></p>'
            '</section>'
        )

    def _upload_default_thumb(self, token: str) -> str:
        """生成并上传默认封面图，返回 thumb_media_id。"""
        if self._default_thumb_media_id:
            return self._default_thumb_media_id

        # Generate a simple 900x383 cover image
        import struct
        import zlib

        width, height = 900, 383
        # Create minimal PNG with dark blue background
        raw = b""
        for y in range(height):
            raw += b"\x00"  # filter byte
            for x in range(width):
                raw += b"\x1a\x1a\x2e\xff"  # RGBA dark blue

        def make_chunk(chunk_type, data):
            c = chunk_type + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        png = b"\x89PNG\r\n\x1a\n"
        png += make_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        png += make_chunk(b"IDAT", zlib.compress(raw))
        png += make_chunk(b"IEND", b"")

        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "image"}
        files = {"media": ("cover.png", png, "image/png")}
        resp, data = self._post_with_token_retry(url, params=params, files=files)

        if "media_id" not in data:
            raise RuntimeError(f"WeChat upload default thumb failed: {data}")

        self._default_thumb_media_id = data["media_id"]
        logger.info(f"Default thumb uploaded, media_id={data['media_id']}")
        return data["media_id"]

    def upload_image(self, image_path: str) -> str:
        """Upload an image for use in article content, returns URL.

        Uses the /media/uploadimg API which returns a URL for embedding.
        """
        token = self._get_access_token()
        url = f"{self.BASE_URL}/media/uploadimg"
        params = {"access_token": token}

        with open(image_path, "rb") as f:
            files = {"media": (Path(image_path).name, f, "image/png")}
            resp = requests.post(url, params=params, files=files, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if self._is_invalid_token_response(data):
            logger.warning("WeChat access_token invalid during image upload; refreshing and retrying once")
            token = self._refresh_access_token()
            with open(image_path, "rb") as f:
                files = {"media": (Path(image_path).name, f, "image/png")}
                resp = requests.post(url, params={"access_token": token}, files=files, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

        if "url" not in data:
            logger.warning(f"WeChat upload image failed: {data}")
            return ""

        logger.info(f"Image uploaded for article: {data['url'][:50]}...")
        return data["url"]

    def upload_video(self, video_path: str, title: str = "视频素材") -> str:
        """Upload a video to WeChat material library.

        Args:
            video_path: Path to the video file (MP4, ≤10MB)
            title: Video title for the material library

        Returns:
            media_id of the uploaded video, or empty string if failed
        """
        token = self._get_access_token()
        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "video"}

        video_path = Path(video_path)
        if not video_path.exists():
            logger.warning(f"Video file not found: {video_path}")
            return ""

        # Check file size (WeChat limit: 10MB)
        file_size = video_path.stat().st_size
        max_size = 10 * 1024 * 1024  # 10MB
        if file_size > max_size:
            logger.warning(f"Video too large ({file_size / 1024 / 1024:.1f}MB > 10MB), compressing: {video_path}")
            compressed_path = self._compress_video(video_path, max_size)
            if compressed_path:
                video_path = compressed_path
            else:
                logger.warning(f"Video compression failed, skipping: {video_path}")
                return ""

        try:
            with open(video_path, "rb") as f:
                files = {"media": (video_path.name, f, "video/mp4")}
                description = json.dumps({"title": title[:20], "introduction": title[:120]}, ensure_ascii=False)
                data = {"description": description}
                resp = requests.post(url, params=params, files=files, data=data, timeout=max(self.timeout, 60))
            resp.raise_for_status()
            result = resp.json()

            if "media_id" not in result:
                logger.warning(f"WeChat upload video failed: {result}")
                return ""

            logger.info(f"Video uploaded, media_id={result['media_id']}")
            return result["media_id"]
        except Exception as e:
            logger.warning(f"Video upload failed: {e}")
            return ""

    def _compress_video(self, video_path: Path, max_size: int) -> Path | None:
        """Compress video to fit within max_size using ffmpeg.

        Returns path to compressed video, or None if failed.
        """
        import subprocess

        compressed_path = video_path.with_suffix(".compressed.mp4")

        # Try multiple compression levels (crf: lower = better quality, higher = smaller)
        for crf in [32, 36, 40, 44]:
            try:
                cmd = [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-c:v", "libx264", "-crf", str(crf),
                    "-preset", "fast",
                    "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart",
                    str(compressed_path)
                ]
                subprocess.run(cmd, capture_output=True, timeout=180, check=True)

                if compressed_path.exists() and compressed_path.stat().st_size <= max_size:
                    logger.info(f"Video compressed to {compressed_path.stat().st_size / 1024 / 1024:.1f}MB (crf={crf})")
                    return compressed_path
            except Exception as e:
                logger.debug(f"Video compression crf={crf} failed: {e}")
                continue

        # If still too large, try reducing resolution
        try:
            cmd = [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vf", "scale=iw*0.5:ih*0.5",
                "-c:v", "libx264", "-crf", "36",
                "-preset", "fast",
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart",
                str(compressed_path)
            ]
            subprocess.run(cmd, capture_output=True, timeout=180, check=True)

            if compressed_path.exists() and compressed_path.stat().st_size <= max_size:
                logger.info(f"Video compressed (0.5x resolution) to {compressed_path.stat().st_size / 1024 / 1024:.1f}MB")
                return compressed_path
        except Exception as e:
            logger.warning(f"Video resolution reduction failed: {e}")

        return None
