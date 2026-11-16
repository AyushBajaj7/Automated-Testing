import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path when running script directly or as module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError
from app.config import settings
from app.schemas import PostingRequest
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.wordpress import WordPressPlatform
from app.platforms.telegram import TelegramPlatform

PLATFORMS = {
    "bluesky": BlueskyPlatform,
    "mastodon": MastodonPlatform,
    "devto": DevToPlatform,
    "wordpress": WordPressPlatform,
    "telegram": TelegramPlatform,
}


async def run_test(platform_name: str) -> int:
    message = os.getenv("LIVE_TEST_MESSAGE", "").strip()
    if not message:
        print("LIVE_TEST_MESSAGE is missing from .env")
        return 2

    try:
        PostingRequest(message=message)
    except ValidationError as err:
        print(f"Validation failed for LIVE_TEST_MESSAGE: {err}")
        return 1

    key = platform_name.lower().strip()
    platform_cls = PLATFORMS.get(key)
    if not platform_cls:
        print(f"Unknown platform '{platform_name}'. Available: {', '.join(PLATFORMS.keys())}")
        return 2

    platform = platform_cls()
    print(f"\n==================================================")
    print(f" Testing platform: {platform.name}")
    print(f" Message: {message}")
    print(f"==================================================")

    result = await platform.publish(message)

    print(f"Platform:      {result.platform}")
    print(f"Status:        {result.status}")
    print(f"Posted URL:    {result.posted_url}")
    print(f"Public Access: {result.public_access}")
    print(f"Date:          {result.date}")
    print(f"Time:          {result.time}")
    print(f"Error:         {result.error}")
    print(f"==================================================\n")

    if result.status != "success":
        return 1
    if not result.public_access:
        print("Publishing succeeded, but public access was not verified.")
        return 2

    print("Public publishing verified successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Test one platform integration."
    )
    parser.add_argument(
        "platform",
        choices=list(PLATFORMS.keys()),
    )
    parser.add_argument(
        "--confirm-public-post",
        action="store_true",
    )
    args = parser.parse_args()

    if not args.confirm_public_post:
        parser.error(
            "This command publishes a real post. "
            "Add --confirm-public-post to continue."
        )

    exit_code = asyncio.run(
        run_test(args.platform)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
