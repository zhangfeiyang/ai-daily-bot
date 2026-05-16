# src/llm/client.py
import os
import re
import subprocess
from pathlib import Path

from loguru import logger


class LLMClient:
    def __init__(self, config: dict):
        self.config = config
        self.provider = config.get("default", "openai")
        self._provider_configs = config.get("providers", {})
        self._provider_config = self._provider_configs.get(self.provider, {})
        self.api_key = self._provider_config.get("api_key", "")
        self.base_url = self._provider_config.get("base_url", "")
        self.model = self._provider_config.get("model", "")
        self.protocol = self._provider_config.get("protocol", "openai")
        self.timeout = float(self._provider_config.get("timeout", os.environ.get("LLM_TIMEOUT_SECONDS", 120)))
        fallbacks = config.get("fallbacks", {}).get(self.provider, [])
        if isinstance(fallbacks, str):
            fallbacks = [fallbacks]
        self.fallback_providers = [name for name in fallbacks if name != self.provider]

    def _get_provider_config(self, provider: str) -> dict:
        return self._provider_configs.get(provider, {})

    @staticmethod
    def _provider_protocol(provider: str, cfg: dict) -> str:
        return cfg.get("protocol", "anthropic" if provider == "anthropic" else "openai")

    def _generate_for_provider(
        self,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
        temperature: float = None,
    ) -> str:
        cfg = self._get_provider_config(provider)
        if not cfg:
            raise ValueError(f"Missing provider config for {provider}")

        protocol = self._provider_protocol(provider, cfg)
        if protocol == "opencli":
            return self._generate_opencli(
                system_prompt,
                user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                cfg=cfg,
            )
        if protocol == "anthropic":
            return self._generate_anthropic(
                system_prompt,
                user_prompt,
                temperature=temperature,
                cfg=cfg,
                max_tokens=min(max_tokens, 4096),
            )
        return self._generate_openai_compatible(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            cfg=cfg,
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int | None = None,
    ) -> str:
        providers = [self.provider] + [p for p in self.fallback_providers if p != self.provider]
        last_error = None
        for provider in providers:
            for attempt in range(3):
                try:
                    return self._generate_for_provider(
                        provider,
                        system_prompt,
                        user_prompt,
                        max_tokens=max_tokens or 16384,
                        temperature=temperature,
                    )
                except Exception as e:
                    if self._is_timeout_error(e) and attempt < 2:
                        import time
                        logger.warning(f"LLM provider '{provider}' timeout (attempt {attempt + 1}/3), retrying in 15s...")
                        time.sleep(15)
                        last_error = e
                        continue
                    last_error = e
                    logger.warning(f"LLM provider '{provider}' failed: {e}")
                    break
        if last_error:
            raise last_error
        raise RuntimeError("No LLM provider available")

    @staticmethod
    def _is_timeout_error(e: Exception) -> bool:
        """Return True if the exception is a timeout error."""
        err_type = type(e).__name__
        err_str = str(e).lower()
        timeout_names = {"timeout", "readtimeout", "writetimeout", "apitimeouterror", "httpxreadtimeout", "httpxwritetimeout", "httxtimeout", "connecttimeout", "gottimeout"}
        return err_type.lower() in timeout_names or "timeout" in err_str or "timed out" in err_str

    def generate_with_images(self, system_prompt: str, text: str, image_urls: list[str], provider: str = "vision") -> str:
        """Generate response with image inputs using a specified provider."""
        cfg = self._get_provider_config(provider)
        if cfg.get("protocol") == "opencli":
            return self._generate_opencli_with_images(system_prompt, text, image_urls, cfg=cfg)

        if cfg.get("protocol") == "minimax_mcp":
            from src.minimax_mcp import MiniMaxMCPClient

            client = MiniMaxMCPClient(
                api_key=cfg.get("api_key", ""),
                api_host=cfg.get("api_host", "https://api.minimaxi.com"),
                timeout=float(cfg.get("timeout", self.timeout)),
            )
            prompt = f"{system_prompt}\n\n{text}".strip()
            responses = []
            for idx, image_url in enumerate(image_urls, 1):
                response = client.understand_image(
                    f"{prompt}\n\n当前图片编号：{idx}",
                    image_url,
                )
                if response:
                    responses.append(f"{idx}: {response}")
            return "\n".join(responses)

        content = [{"type": "text", "text": text}]
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": self._image_input_url(url)}})
        import openai
        client = openai.OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=self.timeout)
        # Disable streaming for vision calls - some providers don't support it
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            stream=False,
            timeout=self.timeout,
        )
        return response.choices[0].message.content or ""

    def _generate_opencli(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
        temperature: float = None,
        cfg: dict | None = None,
        extra_args: list[str] | None = None,
    ) -> str:
        """Generate text through an OpenCLI browser-backed chat adapter."""
        cfg = cfg or self._provider_config
        site = cfg.get("site") or cfg.get("command") or cfg.get("name")
        if not site:
            raise ValueError("OpenCLI provider requires a 'site' value")

        timeout_seconds = int(cfg.get("timeout", self.timeout) or self.timeout)
        prompt = self._compose_opencli_prompt(system_prompt, user_prompt, max_tokens=max_tokens, temperature=temperature)

        cmd = ["opencli", site, "ask", prompt, "--timeout", str(timeout_seconds), "-f", "plain"]
        if cfg.get("new"):
            if site == "chatgpt":
                cmd.append("--new")
            elif site in {"gemini", "deepseek"}:
                cmd.extend(["--new", "true"])

        if site == "deepseek":
            model = cfg.get("model")
            if model:
                cmd.extend(["--model", str(model)])
            if cfg.get("think"):
                cmd.extend(["--think", "true"])
            if cfg.get("search"):
                cmd.extend(["--search", "true"])

        if extra_args:
            cmd.extend(extra_args)

        logger.info(f"Calling OpenCLI LLM provider '{site}'")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds + 30, timeout_seconds),
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            raise RuntimeError(f"opencli {site} ask failed ({proc.returncode}): {stderr or stdout}")

        content = (proc.stdout or "").strip()
        if not content:
            raise RuntimeError(f"Empty response from opencli provider '{site}'")
        return self._strip_model_artifacts(content)

    def _generate_opencli_with_images(
        self,
        system_prompt: str,
        text: str,
        image_urls: list[str],
        cfg: dict | None = None,
    ) -> str:
        """Use OpenCLI for vision review without falling back to API providers."""
        cfg = cfg or {}
        site = cfg.get("site") or cfg.get("command") or "deepseek"
        image_lines = "\n".join(f"{idx}. {url}" for idx, url in enumerate(image_urls or [], 1))
        prompt = (
            f"{text}\n\n"
            "图片输入：\n"
            f"{image_lines}\n\n"
            "请结合上面的图片输入完成任务。"
        ).strip()

        extra_args: list[str] = []
        if site == "deepseek":
            local_images = [url for url in image_urls or [] if url and not url.startswith(("http://", "https://", "data:"))]
            if local_images:
                path = Path(local_images[0])
                if path.exists():
                    extra_args.extend(["--file", str(path)])

        return self._generate_opencli(system_prompt, prompt, cfg=cfg, extra_args=extra_args)

    @staticmethod
    def _compose_opencli_prompt(
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
        temperature: float = None,
    ) -> str:
        parts = []
        if system_prompt:
            parts.append("【系统要求】\n" + system_prompt.strip())
        if user_prompt:
            parts.append("【用户输入】\n" + user_prompt.strip())
        if temperature is not None:
            parts.append(f"【生成参数】temperature={temperature}")
        if max_tokens:
            parts.append(f"【长度上限】最多约 {max_tokens} tokens。")
        return "\n\n---\n\n".join(parts).strip()

    @staticmethod
    def _strip_model_artifacts(content: str) -> str:
        content = re.sub(r'<(?:think|thinking)\b[^>]*>.*?</(?:think|thinking)>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<(?:think|thinking)\b[^>]*>.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'^```(?:html|markdown|md)?\s*', '', content.strip(), flags=re.IGNORECASE)
        content = re.sub(r'\s*```$', '', content.strip())
        content = re.sub(r'<>?\(.*?\)', '', content)
        content = re.sub(r'^(?:💬|🤖)\s*', '', content)
        content = re.sub(r'^(?:Gemini|ChatGPT|DeepSeek|Doubao)\s*[:：]\s*', '', content, flags=re.IGNORECASE)
        return content.strip()

    @staticmethod
    def _image_input_url(url: str) -> str:
        if url.startswith(("http://", "https://", "data:")):
            return url

        from pathlib import Path
        import base64
        import mimetypes

        path = Path(url)
        if not path.exists():
            return url

        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _generate_openai_compatible(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
        temperature: float = None,
        cfg: dict | None = None,
    ) -> str:
        import openai
        cfg = cfg or self._provider_config
        client = openai.OpenAI(api_key=cfg.get("api_key", self.api_key), base_url=cfg.get("base_url", self.base_url), timeout=self.timeout)
        kwargs = {
            "model": cfg.get("model", self.model),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "stream": False,
            "timeout": self.timeout,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = client.chat.completions.create(**kwargs)
        if hasattr(response, "choices"):
            content = response.choices[0].message.content or ""
        else:
            chunks = []
            for chunk in response:
                try:
                    delta = chunk.choices[0].delta.content
                except Exception:
                    delta = None
                if delta:
                    chunks.append(delta)
            content = "".join(chunks)
        if not content.strip():
            raise RuntimeError("Empty response from openai-compatible provider")
        # 去除推理标记。部分兼容接口会把 reasoning 泄漏到 content。
        return self._strip_model_artifacts(content)

    def _generate_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        cfg: dict | None = None,
        max_tokens: int = 4096,
    ) -> str:
        import anthropic
        cfg = cfg or self._provider_config
        client = anthropic.Anthropic(api_key=cfg.get("api_key", self.api_key), base_url=cfg.get("base_url", self.base_url), timeout=self.timeout)
        kwargs = {
            "model": cfg.get("model", self.model),
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "timeout": self.timeout,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = client.messages.create(**kwargs)
        # Find the first text block (skip thinking blocks)
        text_content = None
        for block in response.content:
            if hasattr(block, 'text'):
                text_content = block.text
                break
        if not text_content or not text_content.strip():
            raise RuntimeError("Empty response from anthropic provider")
        return text_content
