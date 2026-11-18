import asyncio
import logging
import random
from typing import Sequence, Optional
from pydantic import BaseModel
from app.platforms.base import BasePlatform, PlatformResult
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.wordpress import WordPressPlatform
from app.platforms.telegram import TelegramPlatform
from app.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Bounded concurrency limiter (prevents socket/file-descriptor exhaustion under high load)
MAX_CONCURRENT_REQUESTS = 20
GLOBAL_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

# Circuit breaker registry for fault tolerance against third-party outages
CIRCUIT_BREAKERS: dict[str, CircuitBreaker] = {
    "Bluesky": CircuitBreaker("Bluesky", failure_threshold=5, recovery_timeout=60.0),
    "Mastodon": CircuitBreaker("Mastodon", failure_threshold=5, recovery_timeout=60.0),
    "DEV.to": CircuitBreaker("DEV.to", failure_threshold=5, recovery_timeout=60.0),
    "WordPress": CircuitBreaker("WordPress", failure_threshold=5, recovery_timeout=60.0),
    "Telegram": CircuitBreaker("Telegram", failure_threshold=5, recovery_timeout=60.0),
}


class PostingResponse(BaseModel):
    success: bool
    total_platforms: int
    successful: int
    failed: int
    results: list[PlatformResult]


PLATFORMS: list[BasePlatform] = [
    BlueskyPlatform(),
    MastodonPlatform(),
    DevToPlatform(),
    WordPressPlatform(),
    TelegramPlatform(),
]


def is_transient_failure(error: str | None) -> bool:
    """Classifies whether a failure represents a transient infrastructure/network condition.

    Transient faults (which trip the Circuit Breaker):
      - Network connectivity / timeouts (httpx.TimeoutException, httpx.RequestError)
      - HTTP 5xx Server Errors (500, 502, 503, 504)
      - HTTP 429 Too Many Requests (rate limiting)
      - Unexpected runtime system exceptions

    Permanent faults (which do NOT trip the Circuit Breaker):
      - Missing credentials / unconfigured platforms
      - Authentication and authorization errors (HTTP 401, 403)
      - Bad request / client validation errors (HTTP 400, 422)
      - Resource not found (HTTP 404)
      - Misconfigured HTTPS or URL format
    """
    if not error:
        return False

    err = error.lower()

    # 1. Permanent configuration and credentials issues
    if (
        "not configured" in err
        or "authentication failed" in err
        or "invalid authentication" in err
        or "credentials" in err
        or "must use https" in err
        or "no valid url found" in err
        or "must not contain credentials" in err
    ):
        return False

    # 2. Permanent HTTP 4xx Client Errors (except 429 Too Many Requests)
    for code in [400, 401, 403, 404, 405, 409, 410, 413, 422]:
        if f"http {code}" in err or f"({code})" in err:
            return False

    if "unauthorized" in err or "forbidden" in err:
        return False

    # 3. Explicit transient indicators
    if (
        "timed out" in err
        or "timeout" in err
        or "network error" in err
        or "connection" in err
        or "connecterror" in err
        or "readtimeout" in err
        or "unexpected error" in err
        or "500" in err
        or "502" in err
        or "503" in err
        or "504" in err
        or "429" in err
        or "too many requests" in err
        or "service unavailable" in err
        or "bad gateway" in err
        or "gateway timeout" in err
    ):
        return True

    return False


async def publish_with_retry_and_backoff(
    platform: BasePlatform,
    message: str,
    max_retries: int = 1,
    base_backoff: float = 0.2,
) -> PlatformResult:
    """Executes platform publishing with exponential backoff and full jitter for transient faults."""
    attempt = 0
    while True:
        try:
            result = await platform.publish(message)
            return result
        except Exception as exc:
            attempt += 1
            if attempt > max_retries:
                raise exc

            # AWS Full Jitter Algorithm: sleep = random_between(0, min(max_delay, base * 2^attempt))
            sleep_duration = random.uniform(0, min(2.0, base_backoff * (2 ** attempt)))
            logger.info(
                "Transient error on %s: %s. Retrying in %.2fs (attempt %d/%d)",
                platform.name,
                type(exc).__name__,
                sleep_duration,
                attempt,
                max_retries,
            )
            await asyncio.sleep(sleep_duration)


async def publish_safely(
    platform: BasePlatform,
    message: str,
) -> PlatformResult:
    """Isolates platform execution with Circuit Breaker, Semaphore, and safe error handling."""
    breaker = CIRCUIT_BREAKERS.get(platform.name)

    # 1. Circuit Breaker Check: Fast-fail if remote dependency is down
    if breaker and not breaker.can_execute():
        logger.warning(
            "Circuit Breaker is OPEN for %s. Failing fast without network overhead.",
            platform.name,
        )
        return platform.failure(
            f"Circuit breaker is OPEN: {platform.name} is temporarily unreachable."
        )

    # 2. Bounded Concurrency Check: Limit simultaneous active outbound sockets
    try:
        async with GLOBAL_SEMAPHORE:
            # Direct single-attempt execution prevents duplicate post creation on non-idempotent endpoints
            result = await platform.publish(message)

        if result.status == "success":
            if breaker:
                breaker.record_success()
        else:
            # Trip circuit breaker only on transient infrastructure/network failures
            if breaker and is_transient_failure(result.error):
                breaker.record_failure()

        return result

    except Exception as exc:
        logger.error(
            "Unhandled exception while posting to %s: %s",
            platform.name,
            type(exc).__name__,
        )
        if breaker:
            breaker.record_failure()
        return platform.failure(f"Unexpected error: {type(exc).__name__}")


async def publish_message(
    message: str,
    platforms: Optional[Sequence[BasePlatform]] = None,
) -> PostingResponse:
    """Coordinates parallel broadcast to all platforms using Scatter-Gather pattern."""
    target_platforms = list(platforms) if platforms is not None else PLATFORMS

    # Scatter: fan-out across platforms concurrently
    tasks = [
        publish_safely(platform, message)
        for platform in target_platforms
    ]
    # Gather: fan-in and await resolution
    results: list[PlatformResult] = await asyncio.gather(*tasks)

    successful = sum(
        1 for result in results
        if result.status == "success"
    )
    total = len(target_platforms)
    failed = total - successful
    is_success = successful > 0

    return PostingResponse(
        success=is_success,
        total_platforms=total,
        successful=successful,
        failed=failed,
        results=results,
    )
