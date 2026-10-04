"""Isolated optional OpenAI-compatible LLM adapter."""

from __future__ import annotations

import json
from urllib import error, request

from app.config import LLM_API_KEY, LLM_API_URL, LLM_MODEL, LLM_PROVIDER


class LLMNotConfiguredError(RuntimeError):
    """Raised when recruiter chat has no provider configuration."""


class LLMProviderError(RuntimeError):
    """Raised when the configured provider cannot answer."""


def generate_grounded_answer(system_prompt: str, user_message: str) -> str:
    """Generate an answer through the configured OpenAI-compatible provider."""

    if not LLM_PROVIDER or not LLM_API_KEY or not LLM_MODEL:
        raise LLMNotConfiguredError("Recruiter chat is not configured")
    if LLM_PROVIDER.casefold() not in {"openai", "openai-compatible", "openai_compatible"}:
        raise LLMProviderError("Configured recruiter chat provider is not supported")

    payload = json.dumps(
        {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0,
        }
    ).encode("utf-8")
    http_request = request.Request(
        LLM_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, error.HTTPError, TimeoutError, ValueError) as provider_error:
        raise LLMProviderError("Recruiter chat provider request failed") from provider_error

    try:
        answer = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as provider_error:
        raise LLMProviderError("Recruiter chat provider returned an invalid response") from provider_error
    if not isinstance(answer, str) or not answer.strip():
        raise LLMProviderError("Recruiter chat provider returned an empty response")
    return answer.strip()
