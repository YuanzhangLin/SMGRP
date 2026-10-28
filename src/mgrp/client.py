"""Minimal OpenAI-compatible chat client used by MGRP."""

from __future__ import annotations

import base64
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _setting(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, candidate = line.split("=", 1)
            if key.strip() == name:
                parsed = candidate.strip().strip('"').strip("'")
                return parsed or default
    return default


@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class OpenAICompatibleClient:
    def __init__(self, *, api_key=None, base_url=None, model=None):
        self._explicit_api_key = api_key
        self._explicit_base_url = base_url
        self.api_key = api_key or _setting("MGRP_LLM_API_KEY") or _setting("DASHSCOPE_API_KEY")
        self.base_url = base_url or _setting("MGRP_LLM_BASE_URL") or _setting("DASHSCOPE_BASE_URL")
        self.model = model or _setting("MGRP_LLM_MODEL", "qwen-max") or "qwen-max"

    def _provider(self, model: str) -> tuple[str | None, str | None]:
        if self._explicit_api_key or self._explicit_base_url or _setting("MGRP_LLM_API_KEY") or _setting("MGRP_LLM_BASE_URL"):
            return self.api_key, self.base_url
        if model.lower().startswith("gpt-"):
            # GPT experiments may use the explicitly configured Hi-Code
            # OpenAI-compatible relay. Prefer that named configuration so an
            # unrelated OpenRouter key cannot silently capture these runs.
            key = _setting("HICODE_API_KEY") or _setting("OPENAI_API_KEY")
            base_url = _setting("HICODE_BASE_URL") or _setting("OPENAI_BASE_URL")
            if not base_url and key and key.startswith("sk-or-"):
                base_url = "https://openrouter.ai/api/v1"
            return key, base_url or "https://api.openai.com/v1"
        if model.lower().startswith("deepseek-"):
            return (_setting("DEEPSEEK_API_KEY"),
                    _setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        return self.api_key, self.base_url

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, *, system: str, user: str, model: str | None = None,
                 json_mode: bool = True, image_path: Path | None = None) -> ChatResponse:
        selected = model or self.model
        api_key, base_url = self._provider(selected)
        if not api_key:
            raise RuntimeError(f"No API key configured for model provider: {selected}")
        from openai import OpenAI

        user_content: str | list[dict[str, object]] = user
        if image_path is not None:
            media_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            user_content = [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
            ]
        routed_model = selected
        if (base_url and "openrouter.ai" in base_url
                and selected.lower().startswith("gpt-")):
            routed_model = f"openai/{selected}"
        request = {
            "model": routed_model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        if selected.lower().startswith("gpt-5.5"):
            request["reasoning_effort"] = "none"
        # Qwen runs in this experiment are non-reasoning Chat Completions.
        # Disable DeepSeek's default high-thinking mode for a comparable budget.
        if selected.lower().startswith("deepseek-"):
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        timeout = float(_setting("MGRP_LLM_TIMEOUT_SECONDS", "180") or "180")
        response = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1).chat.completions.create(**request)
        usage = response.usage
        return ChatResponse(
            content=(response.choices[0].message.content or "").strip(),
            model=selected,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
