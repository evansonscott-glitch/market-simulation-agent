"""
LLM Client — Wrapper for OpenAI-compatible API calls.
Handles retries, rate limiting, and concurrent execution.
"""
import asyncio
import random
import time
from openai import OpenAI, AsyncOpenAI
from typing import List, Dict, Any, Optional


def get_sync_client() -> OpenAI:
    return OpenAI()


def get_async_client() -> AsyncOpenAI:
    return AsyncOpenAI()


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict] = None,
) -> str:
    """Synchronous chat completion with retry logic."""
    client = get_sync_client()
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                print(f"  [LLM] Retry {attempt + 1}/{max_retries} after error: {e}")
                time.sleep(wait_time)
            else:
                raise


async def async_chat_completion(
    client: AsyncOpenAI,
    messages: List[Dict[str, str]],
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict] = None,
) -> str:
    """Async chat completion with exponential backoff and jitter."""
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            error_str = str(e)
            is_rate_limit = "429" in error_str or "rate" in error_str.lower()
            if attempt < max_retries - 1:
                if is_rate_limit:
                    wait_time = (2 ** (attempt + 2)) + random.uniform(1, 5)
                else:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(wait_time)
            else:
                raise


async def run_concurrent_completions(
    tasks: List[Dict[str, Any]],
    max_concurrent: int = 10,
) -> List[str]:
    """
    Run multiple chat completions concurrently with a semaphore.
    Each task dict: {messages, model, temperature, max_tokens, response_format}.
    Returns results in same order as tasks.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    client = get_async_client()
    results = [None] * len(tasks)

    async def run_one(index: int, task: Dict):
        async with semaphore:
            result = await async_chat_completion(
                client=client,
                messages=task["messages"],
                model=task.get("model", "gemini-2.5-flash"),
                temperature=task.get("temperature", 0.7),
                max_tokens=task.get("max_tokens", 4096),
                response_format=task.get("response_format"),
            )
            results[index] = result

    await asyncio.gather(*[run_one(i, t) for i, t in enumerate(tasks)])
    await client.close()
    return results
