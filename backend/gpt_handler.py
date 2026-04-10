import logging
from typing import List
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def generate_reply(openai_key: str, model: str, system_prompt: str, history: List) -> str:
    """Generate a GPT reply based on conversation history."""
    client = AsyncOpenAI(api_key=openai_key)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg.role, "content": msg.text})

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return ""
