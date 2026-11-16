import asyncio
from pydantic import BaseModel
from app.platforms.base import BasePlatform, PlatformResult
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.wordpress import WordPressPlatform
from app.platforms.telegram import TelegramPlatform


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


async def publish_safely(
    platform: BasePlatform,
    message: str,
) -> PlatformResult:
    try:
        return await platform.publish(message)
    except Exception as exc:
        return platform.failure(f"Unexpected error: {str(exc)}")


async def publish_message(
    message: str,
    platforms: list[BasePlatform] | None = None,
) -> PostingResponse:
    target_platforms = platforms if platforms is not None else PLATFORMS

    tasks = [
        publish_safely(platform, message)
        for platform in target_platforms
    ]
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
