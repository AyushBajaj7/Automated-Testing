import httpx
import re
from app.config import settings
from app.platforms.base import BasePlatform, PlatformResult
from app.schemas import URL_PATTERN


class DevToPlatform(BasePlatform):
    name = "DEV.to"

    async def publish(self, message: str) -> PlatformResult:
        if not settings.DEVTO_API_KEY:
            return self.failure(
                "DEV.to API key is not configured."
            )

        title_text = URL_PATTERN.sub("", message)
        title_text = re.sub(r"\s+", " ", title_text).strip(
            " \t\r\n-—:;,.!?"
        )
        title = re.split(
            r"(?<=[.!?])\s+", title_text, maxsplit=1
        )[0].strip()

        if not title or len(title) < 5:
            title = f"Update: {title}".strip() if title else "A quick update"

        if len(title) > 120:
            title = title[:117].rsplit(" ", 1)[0] + "..."

        article = {
            "article": {
                "title": title,
                "body_markdown": message,
                "published": True,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://dev.to/api/articles",
                    headers={
                        "api-key": settings.DEVTO_API_KEY,
                        "Accept": "application/vnd.forem.api-v1+json",
                    },
                    json=article,
                )

                if not response.is_success:
                    return self.failure(
                        "Publishing failed: " + self.get_error(response)
                    )

                data = response.json()
                if not isinstance(data, dict):
                    return self.failure(
                        "Invalid DEV.to API response."
                    )

                posted_url = data.get("url")
                if (
                    not isinstance(posted_url, str)
                    or not posted_url.startswith("https://dev.to/")
                ):
                    return self.failure(
                        "DEV.to did not return a valid article URL."
                    )

                published = (
                    data.get("published") is True
                    or data.get("published_at") is not None
                )

                if not published:
                    return self.failure(
                        "DEV.to did not confirm article publication."
                    )

                article_id = data.get("id")
                # Conclusive public verification via public article endpoint
                try:
                    verify_resp = await client.get(
                        f"https://dev.to/api/articles/{article_id}",
                        timeout=10.0,
                    )
                    public_access = verify_resp.is_success and verify_resp.json().get("published") is True
                except (httpx.TimeoutException, httpx.RequestError):
                    public_access = await self.verify_public_access(
                        client,
                        posted_url,
                    )
                result = self.success(
                    url=posted_url,
                    public_access=public_access,
                )
                if not public_access:
                    result.error = "Article published, but public access could not be verified."
                return result

        except httpx.TimeoutException:
            return self.failure(
                "DEV.to API request timed out."
            )
        except httpx.RequestError as error:
            return self.failure(
                f"DEV.to network error: {type(error).__name__}"
            )
        except (ValueError, TypeError):
            return self.failure(
                "DEV.to returned an invalid response."
            )
