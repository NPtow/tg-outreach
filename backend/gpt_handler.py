import logging
from typing import List

logger = logging.getLogger(__name__)


def _uses_max_completion_tokens(model: str) -> bool:
    normalized = (model or "").lower()
    return normalized.startswith(("gpt-5", "o3", "o4"))


async def generate_reply(
    provider: str,
    openai_key: str,
    anthropic_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    history: List,
) -> str:
    """Generate a reply using the configured AI provider."""

    if provider == "anthropic":
        return await _anthropic_reply(anthropic_key, model, system_prompt, history)
    else:
        # openai-compatible: openai, openrouter, ollama, lmstudio
        return await _openai_compatible_reply(provider, openai_key, base_url, model, system_prompt, history)


async def _anthropic_reply(api_key: str, model: str, system_prompt: str, history: List) -> str:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        messages = [{"role": msg.role, "content": msg.text} for msg in history]
        response = await client.messages.create(
            model=model,
            max_tokens=500,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Anthropic error: {e}")
        return ""


async def _openai_compatible_reply(
    provider: str,
    openai_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    history: List,
) -> str:
    try:
        from openai import AsyncOpenAI

        # Determine base URL per provider
        if not base_url:
            if provider == "ollama":
                base_url = "http://localhost:11434/v1"
            elif provider == "lmstudio":
                base_url = "http://localhost:1234/v1"
            elif provider == "openrouter":
                base_url = "https://openrouter.ai/api/v1"

        # Key selection
        if provider == "openrouter":
            api_key = openai_key  # openrouter key stored in openai_key field
        elif provider == "openai":
            api_key = openai_key
        else:
            api_key = openai_key or "local"

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        client = AsyncOpenAI(**kwargs)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({"role": msg.role, "content": msg.text})

        request_kwargs = {
            "model": model,
            "messages": messages,
        }
        if _uses_max_completion_tokens(model):
            request_kwargs["max_completion_tokens"] = 500
        else:
            request_kwargs["max_tokens"] = 500
            request_kwargs["temperature"] = 0.7

        response = await client.chat.completions.create(**request_kwargs)
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI-compatible ({provider}) error: {e}")
        return ""
