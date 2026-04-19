# src/publish/wechat.py
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
        audio_media_id: str = "",
        thumb_media_id: str = "",
    ) -> str:
        token = self._get_access_token()
        body = content
        if audio_media_id:
            body += f'\n<mpvoice voice_encode_fileid="{audio_media_id}" />'

        draft_url = f"{self.BASE_URL}/draft/add"
        draft_data = {
            "access_token": token,
            "articles": [
                {
                    "title": title,
                    "author": "AI科技前沿",
                    "content": body,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 1,
                }
            ],
        }
        resp = requests.post(draft_url, json=draft_data)
        resp.raise_for_status()
        draft = resp.json()

        if "media_id" not in draft:
            raise RuntimeError(f"WeChat create draft failed: {draft}")

        logger.info(f"Draft created, media_id={draft['media_id']}")

        pub_url = f"{self.BASE_URL}/freepublish/submit"
        pub_data = {"access_token": token, "media_id": draft["media_id"]}
        resp = requests.post(pub_url, json=pub_data)
        resp.raise_for_status()
        pub = resp.json()

        if "publish_id" not in pub:
            raise RuntimeError(f"WeChat publish failed: {pub}")

        logger.info(f"Article published, publish_id={pub['publish_id']}")
        return pub["publish_id"]
