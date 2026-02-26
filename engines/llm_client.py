"""
LLM Client — Hardened Wrapper for OpenAI-compatible API calls.

Handles:
  - Proper retry logic with exponential backoff and jitter
  - Token-aware rate limiting (respects API rate limits)
  - Structured error handling with specific exception types
  - Concurrent execution with semaphore-based throttling
  - Proper logging (no print statements, no API key exposure)
"""
import asyncio
import random
import time
from typing import List, Dict, Any, Optional

from openai import OpenAI, AsyncOpenAI, APIError, RateLimitError, APIConnectionError, APITimeoutError

from engines.logging_config import get_logger

logger = get_logger(__name__)


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

    Respects OpenAI-style rate limits:
      - Requests per minute (RPM)
      - Tokens per minute (TPM)

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
        """
        Wait until we can safely make a request within rate limits.

        Args:
            estimated_tokens: Estimated token usage for this request.
        """
        async with self._lock:
            now = time.monotonic()
            window = 60.0  # 1-minute sliding window

            # Clean old entries
            self.request_timestamps = [
                t for t in self.request_timestamps if now - t < window
            ]
            self.token_usage = [
                (t, tokens) for t, tokens in self.token_usage if now - t < window
            ]

            # Check RPM
            while len(self.request_timestamps) >= self.max_rpm:
                oldest = self.request_timestamps[0]
                wait_time = window - (now - oldest) + 0.1
                if wait_time > 0:
                    logger.debug(
                        "Rate limit: RPM at %d/%d, waiting %.1fs",
                        len(self.request_timestamps), self.max_rpm, wait_time,
                    )
                    await asyncio.sleep(wait_time)
                now = time.monotonic()
                self.request_timestamps = [
                    t for t in self.request_timestamps if now - t < window
                ]

            # Check TPM
            current_tpm = sum(tokens for _, tokens in self.token_usage)
            while current_tpm + estimated_tokens > self.max_tpm:
                if self.token_usage:
                    oldest_t = self.token_usage[0][0]
                    wait_time = window - (now - oldest_t) + 0.1
                else:
                    wait_time = 1.0
                if wait_time > 0:
                    logger.debug(
                        "Rate limit: TPM at %d/%d, waiting %.1fs",
                        current_tpm, self.max_tpm, wait_time,
                    )
                    await asyncio.sleep(wait_time)
                now = time.monotonic()
                self.token_usage = [
                    (t, tokens) for t, tokens in self.token_usage if now - t < window
                ]
                current_tpm = sum(tokens for _, tokens in self.token_usage)

            # Record this request
            self.request_timestamps.append(now)
            self.token_usage.append((now, estimated_tokens))

    async def record_actual_usage(self, tokens: int) -> None:
        """Update with actual token usage after a response."""
        async with self._lock:
            now = time.monotonic()
            # Replace the estimated entry with actual
            if self.token_usage:
                self.token_usage[-1] = (now, tokens)

    async def record_rate_limit_hit(self) -> float:
        """
        Record that we hit a rate limit. Returns recommended wait time.
        Uses adaptive backoff — consecutive hits increase wait time.
        """
        async with self._lock:
            self._consecutive_rate_limits += 1
            wait_time = min(
                2 ** self._consecutive_rate_limits + random.uniform(1, 3),
                60.0,  # Cap at 60 seconds
            )
            logger.warning(
                "Rate limit hit (consecutive: %d), backing off %.1fs",
                self._consecutive_rate_limits, wait_time,
            )
            return wait_time

    async def record_success(self) -> None:
        """Record a successful request (resets consecutive rate limit counter)."""
        async with self._lock:
            self._consecutive_rate_limits = 0


# ── Global rate limiter instance ──
_rate_limiter: Optional[TokenAwareRateLimiter] = None


def get_rate_limiter() -> TokenAwareRateLimiter:
    """Get or create the global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenAwareRateLimiter()
    return _rate_limiter


def configure_rate_limiter(max_rpm: int = 500, max_tpm: int = 200_000) -> None:
    """Configure the global rate limiter with custom limits."""
    global _rate_limiter
    _rate_limiter = TokenAwareRateLimiter(max_rpm=max_rpm, max_tpm=max_tpm)
    logger.info("Rate limiter configured: RPM=%d, TPM=%d", max_rpm, max_tpm)


# ──────────────────────────────────────────────
# Client Factories
# ──────────────────────────────────────────────

def get_sync_client() -> OpenAI:
    """Create a synchronous OpenAI client."""
    return OpenAI()


def get_async_client() -> AsyncOpenAI:
    """Create an async OpenAI client."""
    return AsyncOpenAI()


# ──────────────────────────────────────────────
# Retry Logic
# ──────────────────────────────────────────────

def _classify_error(error: Exception) -> tuple:
    """
    Classify an API error to determine retry behavior.

    Returns:
        (is_retryable: bool, is_rate_limit: bool, description: str)
    """
    if isinstance(error, RateLimitError):
        return True, True, "rate_limit"
    elif isinstance(error, APITimeoutError):
        return True, False, "timeout"
    elif isinstance(error, APIConnectionError):
        return True, False, "connection_error"
    elif isinstance(error, APIError):
        status = getattr(error, "status_code", None)
        if status == 429:
            return True, True, "rate_limit_429"
        elif status and status >= 500:
            return True, False, f"server_error_{status}"
        elif status and status >= 400:
            return False, False, f"client_error_{status}"
        return True, False, f"api_error_{status}"
    else:
        # Unknown errors — check for common patterns in message
        error_str = str(error).lower()
        if "429" in error_str or "rate" in error_str:
            return True, True, "rate_limit_inferred"
        elif "timeout" in error_str:
            return True, False, "timeout_inferred"
        elif "connection" in error_str:
            return True, False, "connection_inferred"
        return False, False, "unknown"


def _calculate_backoff(attempt: int, is_rate_limit: bool) -> float:
    """Calculate backoff time with exponential increase and jitter."""
    if is_rate_limit:
        base = 2 ** (attempt + 2)  # Start higher for rate limits
        jitter = random.uniform(1, 5)
    else:
        base = 2 ** attempt
        jitter = random.uniform(0, 1)
    return min(base + jitter, 120.0)  # Cap at 2 minutes


# ──────────────────────────────────────────────
# Core Completion Functions
# ──────────────────────────────────────────────

def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict] = None,
    max_retries: int = 3,
) -> str:
    """
    Synchronous chat completion with retry logic.

    Args:
        messages: Chat messages.
        model: LLM model name.
        temperature: Sampling temperature.
        max_tokens: Max response tokens.
        response_format: Optional response format spec.
        max_retries: Maximum retry attempts.

    Returns:
        The LLM response text.

    Raises:
        LLMRetryExhausted: If all retries fail.
        LLMResponseEmpty: If the response is empty.
    """
    client = get_sync_client()
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content

            if not content or not content.strip():
                raise LLMResponseEmpty(
                    f"LLM returned empty response (model={model}, attempt={attempt + 1})"
                )

            return content

        except LLMResponseEmpty:
            # Retry empty responses
            last_error = LLMResponseEmpty("Empty response")
            if attempt < max_retries - 1:
                wait_time = _calculate_backoff(attempt, False)
                logger.warning(
                    "Empty response on attempt %d/%d, retrying in %.1fs",
                    attempt + 1, max_retries, wait_time,
                )
                time.sleep(wait_time)
            continue

        except Exception as e:
            last_error = e
            is_retryable, is_rate_limit, error_type = _classify_error(e)

            if not is_retryable:
                logger.error(
                    "Non-retryable error (%s): %s",
                    error_type, str(e)[:200],
                )
                raise LLMRetryExhausted(
                    f"Non-retryable error: {error_type}",
                    attempts=attempt + 1,
                    last_error=e,
                ) from e

            if attempt < max_retries - 1:
                wait_time = _calculate_backoff(attempt, is_rate_limit)
                logger.warning(
                    "Retryable error (%s) on attempt %d/%d, retrying in %.1fs",
                    error_type, attempt + 1, max_retries, wait_time,
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "All %d retries exhausted. Last error (%s): %s",
                    max_retries, error_type, str(e)[:200],
                )

    raise LLMRetryExhausted(
        f"All {max_retries} retries exhausted",
        attempts=max_retries,
        last_error=last_error,
    )


async def async_chat_completion(
    client: AsyncOpenAI,
    messages: List[Dict[str, str]],
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict] = None,
    max_retries: int = 5,
) -> str:
    """
    Async chat completion with exponential backoff, jitter, and rate limiting.

    Args:
        client: Async OpenAI client instance.
        messages: Chat messages.
        model: LLM model name.
        temperature: Sampling temperature.
        max_tokens: Max response tokens.
        response_format: Optional response format spec.
        max_retries: Maximum retry attempts.

    Returns:
        The LLM response text.

    Raises:
        LLMRetryExhausted: If all retries fail.
        LLMResponseEmpty: If the response is empty after retries.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    rate_limiter = get_rate_limiter()
    estimated_tokens = max_tokens + sum(len(m.get("content", "")) // 4 for m in messages)

    last_error = None
    for attempt in range(max_retries):
        try:
            # Acquire rate limit slot
            await rate_limiter.acquire(estimated_tokens)

            response = await client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content

            # Record actual token usage if available
            if hasattr(response, "usage") and response.usage:
                total_tokens = response.usage.total_tokens
                await rate_limiter.record_actual_usage(total_tokens)

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
                logger.warning(
                    "Empty response on attempt %d/%d, retrying in %.1fs",
                    attempt + 1, max_retries, wait_time,
                )
                await asyncio.sleep(wait_time)
            continue

        except Exception as e:
            last_error = e
            is_retryable, is_rate_limit, error_type = _classify_error(e)

            if is_rate_limit:
                wait_time = await rate_limiter.record_rate_limit_hit()
            elif not is_retryable:
                logger.error(
                    "Non-retryable error (%s): %s",
                    error_type, str(e)[:200],
                )
                raise LLMRetryExhausted(
                    f"Non-retryable error: {error_type}",
                    attempts=attempt + 1,
                    last_error=e,
                ) from e
            else:
                wait_time = _calculate_backoff(attempt, False)

            if attempt < max_retries - 1:
                logger.warning(
                    "Retryable error (%s) on attempt %d/%d, retrying in %.1fs",
                    error_type, attempt + 1, max_retries, wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "All %d retries exhausted. Last error (%s): %s",
                    max_retries, error_type, str(e)[:200],
                )

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

    Each task dict: {messages, model, temperature, max_tokens, response_format}.
    Failed tasks return None instead of raising (graceful degradation).

    Args:
        tasks: List of task dicts.
        max_concurrent: Maximum concurrent requests.

    Returns:
        Results in same order as tasks. Failed tasks are None.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    client = get_async_client()
    results: List[Optional[str]] = [None] * len(tasks)
    failed_count = 0

    async def run_one(index: int, task: Dict):
        nonlocal failed_count
        async with semaphore:
            try:
                result = await async_chat_completion(
                    client=client,
                    messages=task["messages"],
                    model=task.get("model", "gemini-2.5-flash"),
                    temperature=task.get("temperature", 0.7),
                    max_tokens=task.get("max_tokens", 4096),
                    response_format=task.get("response_format"),
                )
                results[index] = result
            except LLMRetryExhausted as e:
                failed_count += 1
                logger.error(
                    "Task %d/%d failed after %d retries: %s",
                    index + 1, len(tasks), e.attempts, str(e.last_error)[:100],
                )
                results[index] = None
            except Exception as e:
                failed_count += 1
                logger.error("Task %d/%d unexpected error: %s", index + 1, len(tasks), str(e)[:100])
                results[index] = None

    await asyncio.gather(*[run_one(i, t) for i, t in enumerate(tasks)])

    try:
        await client.close()
    except Exception:
        pass  # Don't fail on cleanup

    if failed_count > 0:
        logger.warning(
            "Concurrent completions: %d/%d tasks failed",
            failed_count, len(tasks),
        )

    return results
