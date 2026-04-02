"""
LLM Client — Multi-Backend Wrapper for Anthropic and OpenAI-compatible APIs.

Supports two backends, auto-detected from the model name:
  - Anthropic (Claude models): Uses the Anthropic SDK. Set ANTHROPIC_API_KEY.
  - OpenAI-compatible (Gemini, GPT, etc.): Uses the OpenAI SDK. Set OPENAI_API_KEY.

Detection logic:
  - Model starts with "claude-" → Anthropic backend
  - Everything else → OpenAI backend

Handles:
  - Proper retry logic with exponential backoff and jitter
  - Token-aware rate limiting (respects API rate limits)
  - Structured error handling with specific exception types
  - Concurrent execution with semaphore-based throttling
  - Proper logging (no print statements, no API key exposure)
"""
import asyncio
import os
import random
import time
from typing import List, Dict, Any, Optional

from engines.logging_config import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Backend Detection
# ──────────────────────────────────────────────

def _is_anthropic_model(model: str) -> bool:
    """Check if a model name indicates the Anthropic backend."""
    return model.startswith("claude-")


# ──────────────────────────────────────────────
# Custom Exceptions
# ──────────────────────────────────────────────

class LLMError(Exception):
    """Base exception for LLM client errors."""
    pass


class LLMRetryExhausted(LLMError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(message)


class LLMResponseEmpty(LLMError):
    """Raised when the LLM returns an empty response."""
    pass


# ──────────────────────────────────────────────
# Rate Limiter
# ──────────────────────────────────────────────

class TokenAwareRateLimiter:
    """
    Token-aware rate limiter that tracks requests and tokens per minute.

    Uses a sliding window approach with adaptive backoff when limits are hit.
    """

    def __init__(
        self,
        max_rpm: int = 500,
        max_tpm: int = 200_000,
        safety_margin: float = 0.85,
    ):
        self.max_rpm = int(max_rpm * safety_margin)
        self.max_tpm = int(max_tpm * safety_margin)
        self.request_timestamps: List[float] = []
        self.token_usage: List[tuple] = []  # (timestamp, token_count)
        self._lock = asyncio.Lock()
        self._consecutive_rate_limits = 0

    async def acquire(self, estimated_tokens: int = 1000) -> None:
        """Wait until we can safely make a request within rate limits."""
        async with self._lock:
            now = time.monotonic()
            window = 60.0

            self.request_timestamps = [
                t for t in self.request_timestamps if now - t < window
            ]
            self.token_usage = [
                (t, tokens) for t, tokens in self.token_usage if now - t < window
            ]

            while len(self.request_timestamps) >= self.max_rpm:
                oldest = self.request_timestamps[0]
                wait_time = window - (now - oldest) + 0.1
                if wait_time > 0:
                    logger.debug("Rate limit: RPM at %d/%d, waiting %.1fs",
                                 len(self.request_timestamps), self.max_rpm, wait_time)
                    await asyncio.sleep(wait_time)
                now = time.monotonic()
                self.request_timestamps = [
                    t for t in self.request_timestamps if now - t < window
                ]

            current_tpm = sum(tokens for _, tokens in self.token_usage)
            while current_tpm + estimated_tokens > self.max_tpm:
                if self.token_usage:
                    oldest_t = self.token_usage[0][0]
                    wait_time = window - (now - oldest_t) + 0.1
                else:
                    wait_time = 1.0
                if wait_time > 0:
                    logger.debug("Rate limit: TPM at %d/%d, waiting %.1fs",
                                 current_tpm, self.max_tpm, wait_time)
                    await asyncio.sleep(wait_time)
                now = time.monotonic()
                self.token_usage = [
                    (t, tokens) for t, tokens in self.token_usage if now - t < window
                ]
                current_tpm = sum(tokens for _, tokens in self.token_usage)

            self.request_timestamps.append(now)
            self.token_usage.append((now, estimated_tokens))

    async def record_actual_usage(self, tokens: int) -> None:
        """Update with actual token usage after a response."""
        async with self._lock:
            now = time.monotonic()
            if self.token_usage:
                self.token_usage[-1] = (now, tokens)

    async def record_rate_limit_hit(self) -> float:
        """Record that we hit a rate limit. Returns recommended wait time."""
        async with self._lock:
            self._consecutive_rate_limits += 1
            wait_time = min(
                2 ** self._consecutive_rate_limits + random.uniform(1, 3),
                60.0,
            )
            logger.warning("Rate limit hit (consecutive: %d), backing off %.1fs",
                           self._consecutive_rate_limits, wait_time)
            return wait_time

    async def record_success(self) -> None:
        """Record a successful request (resets consecutive rate limit counter)."""
        async with self._lock:
            self._consecutive_rate_limits = 0


# ── Global rate limiter instance ──
_rate_limiter: Optional[TokenAwareRateLimiter] = None


def get_rate_limiter() -> TokenAwareRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenAwareRateLimiter()
    return _rate_limiter


def configure_rate_limiter(max_rpm: int = 500, max_tpm: int = 200_000) -> None:
    global _rate_limiter
    _rate_limiter = TokenAwareRateLimiter(max_rpm=max_rpm, max_tpm=max_tpm)
    logger.info("Rate limiter configured: RPM=%d, TPM=%d", max_rpm, max_tpm)


# ──────────────────────────────────────────────
# Client Factories
# ──────────────────────────────────────────────

def get_sync_client(model: str = ""):
    """Create a synchronous client for the appropriate backend."""
    if _is_anthropic_model(model):
        from anthropic import Anthropic
        return Anthropic()
    else:
        from openai import OpenAI
        return OpenAI()


def get_async_client(model: str = ""):
    """Create an async client for the appropriate backend."""
    if _is_anthropic_model(model):
        from anthropic import AsyncAnthropic
        return AsyncAnthropic()
    else:
        from openai import AsyncOpenAI
        return AsyncOpenAI()


# ──────────────────────────────────────────────
# Anthropic ↔ OpenAI Message Format Conversion
# ──────────────────────────────────────────────

def _convert_messages_for_anthropic(messages: List[Dict[str, str]]) -> tuple:
    """
    Convert OpenAI-format messages to Anthropic format.

    Anthropic requires:
    - system prompt passed separately (not in messages array)
    - messages array contains only user/assistant alternating turns
    - first message must be from user

    Returns:
        (system_prompt: str, messages: list)
    """
    system_prompt = ""
    anthropic_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_prompt += ("\n\n" + content if system_prompt else content)
        elif role in ("user", "assistant"):
            anthropic_messages.append({"role": role, "content": content})

    # Anthropic requires messages to start with a user turn and alternate.
    # Merge consecutive same-role messages.
    merged = []
    for msg in anthropic_messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(msg)

    # If first message isn't user, prepend a minimal user message
    if not merged or merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "Please proceed."})

    return system_prompt, merged


# ──────────────────────────────────────────────
# Retry Logic
# ──────────────────────────────────────────────

def _classify_error(error: Exception) -> tuple:
    """
    Classify an API error to determine retry behavior.
    Returns: (is_retryable, is_rate_limit, description)
    """
    error_type_name = type(error).__name__
    error_str = str(error).lower()

    # Check for rate limit patterns
    if "ratelimit" in error_type_name.lower() or "429" in error_str or "rate" in error_str:
        return True, True, "rate_limit"

    # Check for timeout patterns
    if "timeout" in error_type_name.lower() or "timeout" in error_str:
        return True, False, "timeout"

    # Check for connection patterns
    if "connection" in error_type_name.lower() or "connection" in error_str:
        return True, False, "connection_error"

    # Check for server errors
    status = getattr(error, "status_code", None)
    if status:
        if status == 429:
            return True, True, "rate_limit_429"
        elif status >= 500:
            return True, False, f"server_error_{status}"
        elif status >= 400:
            return False, False, f"client_error_{status}"

    # Check for overloaded (Anthropic-specific)
    if "overloaded" in error_str:
        return True, False, "overloaded"

    return False, False, "unknown"


def _calculate_backoff(attempt: int, is_rate_limit: bool) -> float:
    if is_rate_limit:
        base = 2 ** (attempt + 2)
        jitter = random.uniform(1, 5)
    else:
        base = 2 ** attempt
        jitter = random.uniform(0, 1)
    return min(base + jitter, 120.0)


# ──────────────────────────────────────────────
# Core Completion Functions
# ──────────────────────────────────────────────

def _call_anthropic_sync(client, messages, model, temperature, max_tokens):
    """Make a synchronous Anthropic API call."""
    system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)

    kwargs = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    # Anthropic temperature range is 0-1
    if temperature is not None:
        kwargs["temperature"] = min(temperature, 1.0)

    response = client.messages.create(**kwargs)

    # Extract text from Anthropic response
    if response.content and len(response.content) > 0:
        return response.content[0].text
    return ""


def _call_openai_sync(client, messages, model, temperature, max_tokens, response_format):
    """Make a synchronous OpenAI API call."""
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


async def _call_anthropic_async(client, messages, model, temperature, max_tokens):
    """Make an async Anthropic API call."""
    system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)

    kwargs = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    if temperature is not None:
        kwargs["temperature"] = min(temperature, 1.0)

    response = await client.messages.create(**kwargs)

    if response.content and len(response.content) > 0:
        text = response.content[0].text
        # Return usage info for rate limiter
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = response.usage.input_tokens + response.usage.output_tokens
        return text, usage
    return "", None


async def _call_openai_async(client, messages, model, temperature, max_tokens, response_format):
    """Make an async OpenAI API call."""
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content

    usage = None
    if hasattr(response, "usage") and response.usage:
        usage = response.usage.total_tokens
    return content, usage


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict] = None,
    max_retries: int = 3,
) -> str:
    """
    Synchronous chat completion with retry logic. Auto-detects backend from model name.

    Args:
        messages: Chat messages (OpenAI format — system/user/assistant roles).
        model: LLM model name. "claude-*" uses Anthropic, everything else uses OpenAI.
        temperature: Sampling temperature.
        max_tokens: Max response tokens.
        response_format: Optional response format (OpenAI only, ignored for Anthropic).
        max_retries: Maximum retry attempts.

    Returns:
        The LLM response text.
    """
    use_anthropic = _is_anthropic_model(model)
    client = get_sync_client(model)

    last_error = None
    for attempt in range(max_retries):
        try:
            if use_anthropic:
                content = _call_anthropic_sync(client, messages, model, temperature, max_tokens)
            else:
                content = _call_openai_sync(client, messages, model, temperature, max_tokens, response_format)

            if not content or not content.strip():
                raise LLMResponseEmpty(
                    f"LLM returned empty response (model={model}, attempt={attempt + 1})"
                )
            return content

        except LLMResponseEmpty:
            last_error = LLMResponseEmpty("Empty response")
            if attempt < max_retries - 1:
                wait_time = _calculate_backoff(attempt, False)
                logger.warning("Empty response on attempt %d/%d, retrying in %.1fs",
                               attempt + 1, max_retries, wait_time)
                time.sleep(wait_time)
            continue

        except Exception as e:
            last_error = e
            is_retryable, is_rate_limit, error_type = _classify_error(e)

            if not is_retryable:
                logger.error("Non-retryable error (%s): %s", error_type, str(e)[:200])
                raise LLMRetryExhausted(
                    f"Non-retryable error: {error_type}",
                    attempts=attempt + 1,
                    last_error=e,
                ) from e

            if attempt < max_retries - 1:
                wait_time = _calculate_backoff(attempt, is_rate_limit)
                logger.warning("Retryable error (%s) on attempt %d/%d, retrying in %.1fs",
                               error_type, attempt + 1, max_retries, wait_time)
                time.sleep(wait_time)
            else:
                logger.error("All %d retries exhausted. Last error (%s): %s",
                             max_retries, error_type, str(e)[:200])

    raise LLMRetryExhausted(
        f"All {max_retries} retries exhausted",
        attempts=max_retries,
        last_error=last_error,
    )


async def async_chat_completion(
    client,
    messages: List[Dict[str, str]],
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict] = None,
    max_retries: int = 5,
) -> str:
    """
    Async chat completion with retry, backoff, and rate limiting.
    Auto-detects backend from model name.
    """
    use_anthropic = _is_anthropic_model(model)
    rate_limiter = get_rate_limiter()
    estimated_tokens = max_tokens + sum(len(m.get("content", "")) // 4 for m in messages)

    last_error = None
    for attempt in range(max_retries):
        try:
            await rate_limiter.acquire(estimated_tokens)

            if use_anthropic:
                content, usage = await _call_anthropic_async(
                    client, messages, model, temperature, max_tokens
                )
            else:
                content, usage = await _call_openai_async(
                    client, messages, model, temperature, max_tokens, response_format
                )

            if usage:
                await rate_limiter.record_actual_usage(usage)

            await rate_limiter.record_success()

            if not content or not content.strip():
                raise LLMResponseEmpty(
                    f"LLM returned empty response (model={model}, attempt={attempt + 1})"
                )
            return content

        except LLMResponseEmpty:
            last_error = LLMResponseEmpty("Empty response")
            if attempt < max_retries - 1:
                wait_time = _calculate_backoff(attempt, False)
                logger.warning("Empty response on attempt %d/%d, retrying in %.1fs",
                               attempt + 1, max_retries, wait_time)
                await asyncio.sleep(wait_time)
            continue

        except Exception as e:
            last_error = e
            is_retryable, is_rate_limit, error_type = _classify_error(e)

            if is_rate_limit:
                wait_time = await rate_limiter.record_rate_limit_hit()
            elif not is_retryable:
                logger.error("Non-retryable error (%s): %s", error_type, str(e)[:200])
                raise LLMRetryExhausted(
                    f"Non-retryable error: {error_type}",
                    attempts=attempt + 1,
                    last_error=e,
                ) from e
            else:
                wait_time = _calculate_backoff(attempt, False)

            if attempt < max_retries - 1:
                logger.warning("Retryable error (%s) on attempt %d/%d, retrying in %.1fs",
                               error_type, attempt + 1, max_retries, wait_time)
                await asyncio.sleep(wait_time)
            else:
                logger.error("All %d retries exhausted. Last error (%s): %s",
                             max_retries, error_type, str(e)[:200])

    raise LLMRetryExhausted(
        f"All {max_retries} retries exhausted",
        attempts=max_retries,
        last_error=last_error,
    )


async def run_concurrent_completions(
    tasks: List[Dict[str, Any]],
    max_concurrent: int = 10,
) -> List[Optional[str]]:
    """
    Run multiple chat completions concurrently with a semaphore.
    Auto-detects backend from model name in each task.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    # Determine backend from first task
    first_model = tasks[0].get("model", "claude-sonnet-4-6") if tasks else "claude-sonnet-4-6"
    client = get_async_client(first_model)
    results: List[Optional[str]] = [None] * len(tasks)
    failed_count = 0

    async def run_one(index: int, task: Dict):
        nonlocal failed_count
        async with semaphore:
            try:
                result = await async_chat_completion(
                    client=client,
                    messages=task["messages"],
                    model=task.get("model", "claude-sonnet-4-6"),
                    temperature=task.get("temperature", 0.7),
                    max_tokens=task.get("max_tokens", 4096),
                    response_format=task.get("response_format"),
                )
                results[index] = result
            except LLMRetryExhausted as e:
                failed_count += 1
                logger.error("Task %d/%d failed after %d retries: %s",
                             index + 1, len(tasks), e.attempts, str(e.last_error)[:100])
                results[index] = None
            except Exception as e:
                failed_count += 1
                logger.error("Task %d/%d unexpected error: %s", index + 1, len(tasks), str(e)[:100])
                results[index] = None

    await asyncio.gather(*[run_one(i, t) for i, t in enumerate(tasks)])

    try:
        await client.close()
    except Exception:
        pass

    if failed_count > 0:
        logger.warning("Concurrent completions: %d/%d tasks failed", failed_count, len(tasks))

    return results
