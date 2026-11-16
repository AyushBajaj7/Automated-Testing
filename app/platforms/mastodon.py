import httpx
import uuid
from app.config import settings
from app.platforms.base import BasePlatform, PlatformResult


class MastodonPlatform(BasePlatform):
    name = "Mastodon"

    async def publish(self, message: str) -> PlatformResult:
        if not settings.MASTODON_BASE_URL or not settings.MASTODON_ACCESS_TOKEN:
            return self.failure(
                "Mastodon credentials are not configured."
            )

        base_url = settings.MASTODON_BASE_URL.rstrip("/")
        if not base_url.startswith("https://"):
            return self.failure(
                "Mastodon instance must use HTTPS."
            )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{base_url}/api/v1/statuses",
                    headers={
                        "Authorization": (
                            f"Bearer {settings.MASTODON_ACCESS_TOKEN}"
                        ),
                        "Idempotency-Key": str(uuid.uuid4()),
                    },
                    data={
                        "status": message,
                        "visibility": "public",
                    },
                )

                if not response.is_success:
                    return self.failure(
                        "Publishing failed: " + self.get_error(response)
                    )

                post_data = response.json()
                if not isinstance(post_data, dict):
                    return self.failure(
                        "Invalid Mastodon API response."
                    )

                posted_url = post_data.get("url")
                visibility = post_data.get("visibility")
                post_id = post_data.get("id")

                if not post_id or visibility != "public":
                    return self.failure(
                        "Mastodon did not confirm a public post."
                    )

                if not isinstance(posted_url, str) or not posted_url.startswith("https://"):
                    return self.failure(
                        "Mastodon did not return a valid public post URL."
                    )

                public_access = await self.verify_public_access(
                    client,
                    posted_url,
                )
                result = self.success(
                    url=posted_url,
                    public_access=public_access,
                )
                if not public_access:
                    result.error = "Post created, but public access could not be verified."
                return result

        except httpx.TimeoutException:
            return self.failure(
                "Mastodon API request timed out."
            )
        except httpx.RequestError as error:
            return self.failure(
                f"Mastodon network error: {type(error).__name__}"
            )
        except (ValueError, TypeError):
            return self.failure(
                "Mastodon returned an invalid response."
            )
