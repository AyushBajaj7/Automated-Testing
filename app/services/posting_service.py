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
                f"Transient error on {platform.name}: {exc}. Retrying in {sleep_duration:.2f}s (attempt {attempt}/{max_retries})"
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
        logger.warning(f"Circuit Breaker is OPEN for {platform.name}. Failing fast without network overhead.")
        return platform.failure(
            f"Circuit breaker is OPEN: {platform.name} is temporarily unreachable."
        )

    # 2. Bounded Concurrency Check: Limit simultaneous active outbound sockets
    try:
        async with GLOBAL_SEMAPHORE:
            result = await publish_with_retry_and_backoff(platform, message, max_retries=1)

        if result.status == "success":
            if breaker:
                breaker.record_success()
        else:
            # Only count as remote failure if it wasn't just "unconfigured"
            if breaker and "not configured" not in str(result.error).lower():
                breaker.record_failure()

        return result

    except Exception as exc:
        logger.error(f"Unhandled exception while posting to {platform.name}: {exc}", exc_info=True)
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
