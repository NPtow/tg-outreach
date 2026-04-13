import logging
from typing import List

logger = logging.getLogger(__name__)


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
        # openai-compatible: openai, ollama, lmstudio
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

        # Determine base URL for local providers
        if not base_url:
            if provider == "ollama":
                base_url = "http://localhost:11434/v1"
            elif provider == "lmstudio":
                base_url = "http://localhost:1234/v1"

        # Local providers don't need a real API key
        api_key = openai_key if provider == "openai" else (openai_key or "local")

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        client = AsyncOpenAI(**kwargs)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({"role": msg.role, "content": msg.text})

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI-compatible ({provider}) error: {e}")
        return ""
