# src/llm/client.py
import os
import re
import copy

from loguru import logger


class LLMClient:
    TEXT_PROVIDER = "minimax"

    def __init__(self, config: dict):
        self.config = config
        self.provider = config.get("default", self.TEXT_PROVIDER)
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

    def clone(self, provider: str | None = None, fallback_providers: list[str] | None = None) -> "LLMClient":
        config = copy.deepcopy(self.config)
        if provider:
            config["default"] = provider
        client = LLMClient(config)
        if fallback_providers is not None:
            client.fallback_providers = [p for p in fallback_providers if p != client.provider]
        return client

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
        thinking: bool | None = None,
    ) -> str:
        cfg = self._get_provider_config(provider)
        if not cfg:
            raise ValueError(f"Missing provider config for {provider}")

        protocol = self._provider_protocol(provider, cfg)
        if protocol == "opencli":
            raise ValueError("OpenCLI browser providers are disabled for text generation")
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
            provider=provider,
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
    ) -> str:
        provider = self.TEXT_PROVIDER
        if provider not in self._provider_configs:
            raise ValueError("MiniMax-M2.7 provider config is required for text generation")
        logger.info(f"Calling text generation provider: {provider}")
        for attempt in range(3):
            try:
                return self._generate_for_provider(
                    provider,
                    system_prompt,
                    user_prompt,
                    max_tokens=max_tokens or 16384,
                    temperature=temperature,
                    thinking=thinking,
                )
            except Exception as e:
                if self._is_timeout_error(e) and attempt < 2:
                    import time
                    logger.warning(f"LLM provider '{provider}' timeout (attempt {attempt + 1}/3), retrying in 15s...")
                    time.sleep(15)
                    continue
                logger.warning(f"LLM provider '{provider}' failed: {e}")
                raise e
        raise RuntimeError("Minimax text generation failed after retries")

    @staticmethod
    def _is_timeout_error(e: Exception) -> bool:
        """Return True if the exception is a timeout error."""
        err_type = type(e).__name__
        err_str = str(e).lower()
        timeout_names = {"timeout", "readtimeout", "writetimeout", "apitimeouterror", "httpxreadtimeout", "httpxwritetimeout", "httxtimeout", "connecttimeout", "gottimeout"}
        return err_type.lower() in timeout_names or "timeout" in err_str or "timed out" in err_str

    def generate_with_images(self, system_prompt: str, text: str, image_urls: list[str], provider: str = "vision") -> str:
        """Generate response with image inputs without using browser chat adapters."""
        cfg = self._get_provider_config(provider)
        if not cfg and provider == "vision":
            minimax_cfg = self._get_provider_config(self.TEXT_PROVIDER)
            cfg = {
                "protocol": "minimax_mcp",
                "api_key": minimax_cfg.get("api_key", ""),
                "api_host": minimax_cfg.get("api_host") or minimax_cfg.get("base_url", "https://api.minimaxi.com").removesuffix("/v1"),
                "timeout": minimax_cfg.get("timeout", self.timeout),
            }
        if not cfg:
            raise ValueError(f"Missing provider config for image understanding: {provider}")
        if cfg.get("protocol") == "opencli":
            raise ValueError("OpenCLI browser providers are disabled for image understanding; only image generation may use web models")
        if (cfg.get("site") or "").lower() == "deepseek":
            raise ValueError("DeepSeek is disabled for image understanding; use MiniMax vision instead")
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
        provider: str = "openai",
    ) -> str:
        import openai
        cfg = cfg or self._provider_config
        api_key = cfg.get("api_key") or self.api_key or os.environ.get(f"{cfg.get('site', '').upper() or provider.upper()}_API_KEY")
        base_url = cfg.get("base_url") or self.base_url
        client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout)
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
        provider_name = cfg.get("site") or provider
        logger.info(f"Calling OpenAI compatible provider '{provider_name}' with model {kwargs.get('model')}")
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"OpenAI compatible client error: {e}")
            raise e
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
        cleaned = self._strip_model_artifacts(content)
        if not cleaned.strip():
            raise RuntimeError("Empty response from openai-compatible provider after cleanup")
        return cleaned

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
