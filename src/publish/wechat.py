# src/publish/wechat.py
import json
import time
from pathlib import Path

import requests
from loguru import logger


class WeChatPublisher:
    BASE_URL = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, config: dict):
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self._token = None
        self._token_expires = 0
        self._default_thumb_media_id = None

    def _get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token

        url = f"{self.BASE_URL}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise RuntimeError(f"WeChat API error: {data}")

        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 7200) - 300
        logger.info("WeChat access_token refreshed")
        return self._token

    def upload_audio(self, audio_path: str) -> str:
        token = self._get_access_token()
        url = f"{self.BASE_URL}/material/add_material"
        params = {"access_token": token, "type": "voice"}

        with open(audio_path, "rb") as f:
            files = {"media": (Path(audio_path).name, f, "audio/mpeg")}
            resp = requests.post(url, params=params, files=files)
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
            resp = requests.post(url, params=params, files=files)
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
        thumb_media_id: str = "",
    ) -> str:
        token = self._get_access_token()

        # Upload audio parts if provided
        if audio_paths:
            for i, ap in enumerate(audio_paths):
                sz = Path(ap).stat().st_size
                if sz <= 2 * 1024 * 1024:
                    media_id = self.upload_audio(ap)
                    logger.info(f"Audio part {i+1}/{len(audio_paths)} uploaded, media_id={media_id}")
                else:
                    logger.warning(f"Audio part {i+1} still too large ({sz/1024/1024:.1f}MB), skipped")

        body = content

        # If no thumb provided, upload a default one
        if not thumb_media_id:
            thumb_media_id = self._upload_default_thumb(token)

        draft_url = f"{self.BASE_URL}/draft/add"
        draft_data = {
            "articles": [
                {
                    "title": title,
                    "author": "张飞洋",
                    "content": body,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 1,
                }
            ],
        }
        resp = requests.post(
            draft_url,
            params={"access_token": token},
            data=json.dumps(draft_data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()
        draft = resp.json()

        if "media_id" not in draft:
            raise RuntimeError(f"WeChat create draft failed: {draft}")

        logger.info(f"Draft created, media_id={draft['media_id']}")

        # Try to publish directly; if unauthorized (subscription account), stop at draft
        pub_url = f"{self.BASE_URL}/freepublish/submit"
        pub_data = {"media_id": draft["media_id"]}
        resp = requests.post(pub_url, params={"access_token": token}, json=pub_data)
        resp.raise_for_status()
        pub = resp.json()

        if pub.get("errcode") == 48001:
            logger.info("freepublish API unauthorized (subscription account). Draft saved, manual publish required.")
            return draft["media_id"]

        if "publish_id" not in pub:
            raise RuntimeError(f"WeChat publish failed: {pub}")

        logger.info(f"Article published, publish_id={pub['publish_id']}")
        return pub["publish_id"]

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
        resp = requests.post(url, params=params, files=files)
        resp.raise_for_status()
        data = resp.json()

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
            resp = requests.post(url, params=params, files=files)
        resp.raise_for_status()
        data = resp.json()

        if "url" not in data:
            logger.warning(f"WeChat upload image failed: {data}")
            return ""

        logger.info(f"Image uploaded for article: {data['url'][:50]}...")
        return data["url"]
