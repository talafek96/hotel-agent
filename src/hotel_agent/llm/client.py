"""LLM client with multi-provider support (OpenAI, Gemini, Anthropic)."""

from __future__ import annotations

import json
import logging
from typing import Any

import litellm

from ..config import AppConfig
from ..utils import strip_code_fences

log = logging.getLogger(__name__)

# Map our provider names to litellm model prefixes
_PROVIDER_PREFIXES = {
    "openai": "",  # No prefix needed
    "gemini": "gemini/",
    "anthropic": "anthropic/",
}


def _get_model_name(provider: str, model: str) -> str:
    """Convert our provider+model to a litellm model string."""
    prefix = _PROVIDER_PREFIXES.get(provider, "")
    # Don't double-prefix
    if model.startswith(prefix):
        return model
    return f"{prefix}{model}"


def _set_api_key(config: AppConfig):
    """Set the appropriate API key as an env var for litellm."""
    import os

    provider = config.llm.provider
    if provider == "openai" and config.openai_api_key:
        os.environ["OPENAI_API_KEY"] = config.openai_api_key
    elif provider == "gemini" and config.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = config.gemini_api_key
    elif provider == "anthropic" and config.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = config.anthropic_api_key


def call_llm(
    config: AppConfig,
    prompt: str,
    system_prompt: str = "",
    model_override: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    response_format: dict | None = None,
) -> str:
    """Call the LLM and return the text response."""
    _set_api_key(config)

    model = model_override or config.llm.model
    model_name = _get_model_name(config.llm.provider, model)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    log.info(f"Calling LLM: model={model_name}, prompt_len={len(prompt)}")

    response = litellm.completion(**kwargs)
    content = response.choices[0].message.content
    log.info(f"LLM response: {len(content)} chars")
    return str(content)


def call_llm_json(
    config: AppConfig,
    prompt: str,
    system_prompt: str = "",
    model_override: str | None = None,
    temperature: float = 0.0,
) -> Any:
    """Call the LLM and parse the response as JSON."""
    response = call_llm(
        config=config,
        prompt=prompt,
        system_prompt=system_prompt,
        model_override=model_override,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    text = strip_code_fences(response)

    return json.loads(text)
