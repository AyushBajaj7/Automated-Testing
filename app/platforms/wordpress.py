import httpx
import re
from urllib.parse import urlsplit
from app.config import settings
from app.platforms.base import BasePlatform, PlatformResult
from app.schemas import URL_PATTERN


class WordPressPlatform(BasePlatform):
    name = "WordPress"

    async def publish(self, message: str) -> PlatformResult:
        if (
            not settings.WORDPRESS_SITE_URL
            or not settings.WORDPRESS_USERNAME
            or not settings.WORDPRESS_APP_PASSWORD
        ):
            return self.failure(
                "WordPress credentials are not configured."
            )

        base_url = settings.WORDPRESS_SITE_URL.rstrip("/")
        parsed_base = urlsplit(base_url)

        if parsed_base.scheme != "https" or not parsed_base.hostname:
            return self.failure(
                "WordPress site must have a valid HTTPS URL."
            )

        if parsed_base.username or parsed_base.password:
            return self.failure(
                "WordPress site URL must not contain credentials."
            )

        clean_message = URL_PATTERN.sub("", message)
        clean_message = re.sub(
            r"\s+", " ", clean_message
        ).strip()
        title = re.split(
            r"(?<=[.!?])\s+", clean_message, maxsplit=1
        )[0].strip(" .!?")

        if not title or len(title) < 5:
            title = f"Post: {title}".strip() if title else "A quick update"

        if len(title) > 120:
            title = title[:117].rsplit(" ", 1)[0] + "..."

        endpoint = (
            f"{base_url}/wp-json/wp/v2/posts"
        )
        app_password = (
            settings.WORDPRESS_APP_PASSWORD.replace(" ", "")
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    endpoint,
                    auth=(
                        settings.WORDPRESS_USERNAME,
                        app_password,
                    ),
                    json={
                        "title": title,
                        "content": message,
                        "status": "publish",
                    },
                )

                if not response.is_success:
                    return self.failure(
                        "Publishing failed: " + self.get_error(response)
                    )

                data = response.json()
                if not isinstance(data, dict):
                    return self.failure(
                        "Invalid WordPress API response."
                    )

                post_id = data.get("id")
                posted_url = data.get("link")
                post_status = data.get("status")

                if not post_id or post_status != "publish":
                    return self.failure(
                        "WordPress did not confirm publication."
                    )

                if (
                    not isinstance(posted_url, str)
                    or not posted_url.startswith("https://")
                ):
                    return self.failure(
                        "WordPress did not return a valid post URL."
                    )

                posted_host = urlsplit(posted_url).hostname
                base_host = parsed_base.hostname

                def normalize_host(host):
                    return host.removeprefix("www.").lower() if host else ""

                public_access = False
                if normalize_host(posted_host) == normalize_host(base_host):
                    # Conclusive public verification via public REST endpoint without credentials
                    try:
                        verify_resp = await client.get(
                            f"{endpoint}/{post_id}",
                            timeout=10.0,
                        )
                        public_access = verify_resp.is_success and verify_resp.json().get("status") == "publish"
                    except (httpx.TimeoutException, httpx.RequestError):
                        public_access = await self.verify_public_access(
                            client,
                            posted_url,
                        )

                result = self.success(
                    url=posted_url, public_access=public_access
                )

                if not public_access:
                    result.error = "Post published, but public access could not be verified."

                return result

        except httpx.TimeoutException:
            return self.failure(
                "WordPress API request timed out."
            )
        except httpx.RequestError as error:
            return self.failure(
                f"WordPress network error: {type(error).__name__}"
            )
        except (ValueError, TypeError):
            return self.failure(
                "WordPress returned an invalid response."
            )
