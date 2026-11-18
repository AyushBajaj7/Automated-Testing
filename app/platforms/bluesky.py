import httpx
import re
from datetime import datetime, timezone
from urllib.parse import quote
from app.config import settings
from app.schemas import URL_PATTERN
from app.platforms.base import BasePlatform, PlatformResult


class BlueskyPlatform(BasePlatform):
    name = "Bluesky"

    async def publish(self, message: str) -> PlatformResult:
        if not settings.BLUESKY_HANDLE or not settings.BLUESKY_APP_PASSWORD:
            return self.failure(
                "Bluesky credentials are not configured."
            )

        service_url = settings.BLUESKY_PDS_URL.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                login_response = await client.post(
                    f"{service_url}/xrpc/com.atproto.server.createSession",
                    json={
                        "identifier": settings.BLUESKY_HANDLE,
                        "password": settings.BLUESKY_APP_PASSWORD,
                    },
                )

                if not login_response.is_success:
                    return self.failure(
                        "Authentication failed: " + self.get_error(login_response)
                    )

                session = login_response.json()
                if not isinstance(session, dict):
                    return self.failure(
                        "Invalid authentication response."
                    )

                access_token = session.get("accessJwt")
                did = session.get("did")

                if not access_token or not did:
                    return self.failure(
                        "Authentication response is missing session details."
                    )

                match = URL_PATTERN.search(message)
                if not match:
                    return self.failure("No valid URL found in the message.")

                url = match.group(0).rstrip(".,!?;:)]}")
                start = match.start()
                end = start + len(url)

                byte_start = len(
                    message[:start].encode("utf-8")
                )
                byte_end = len(
                    message[:end].encode("utf-8")
                )

                created_at = (
                    datetime.now(timezone.utc)
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z")
                )

                record = {
                    "$type": "app.bsky.feed.post",
                    "text": message,
                    "createdAt": created_at,
                    "facets": [
                        {
                            "index": {
                                "byteStart": byte_start,
                                "byteEnd": byte_end,
                            },
                            "features": [
                                {
                                    "$type": "app.bsky.richtext.facet#link",
                                    "uri": url,
                                }
                            ],
                        }
                    ],
                }

                post_response = await client.post(
                    f"{service_url}/xrpc/com.atproto.repo.createRecord",
                    headers={
                        "Authorization": f"Bearer {access_token}"
                    },
                    json={
                        "repo": did,
                        "collection": "app.bsky.feed.post",
                        "record": record,
                    },
                )

                if not post_response.is_success:
                    return self.failure(
                        "Publishing failed: " + self.get_error(post_response)
                    )

                post_data = post_response.json()
                if not isinstance(post_data, dict):
                    return self.failure(
                        "Invalid publishing response."
                    )

                post_uri = post_data.get("uri")
                if not post_uri or not post_uri.startswith("at://"):
                    return self.failure(
                        "Bluesky did not return a valid post URI."
                    )

                post_id = post_uri.rsplit("/", 1)[-1]
                handle = settings.BLUESKY_HANDLE.strip().lstrip("@")
                posted_url = (
                    f"https://bsky.app/profile/"
                    f"{quote(handle, safe='.-')}/post/"
                    f"{quote(post_id, safe='')}"
                )

                # Conclusive public verification via unauthenticated AT Protocol record endpoint
                public_access = False
                try:
                    verify_resp = await client.get(
                        f"{service_url}/xrpc/com.atproto.repo.getRecord",
                        params={
                            "repo": did,
                            "collection": "app.bsky.feed.post",
                            "rkey": post_id,
                        },
                        timeout=10.0,
                    )
                    if getattr(verify_resp, "is_success", False) is True:
                        data = verify_resp.json()
                        public_access = isinstance(data, dict) and data.get("uri") == post_uri
                    else:
                        public_access = False
                except (httpx.TimeoutException, httpx.RequestError):
                    # Fallback to generic HTTP probe only on network transport exception
                    public_access = await self.verify_public_access(
                        client,
                        posted_url,
                    )
                except Exception:
                    public_access = False

                result = self.success(
                    url=posted_url,
                    public_access=public_access,
                )
                if not public_access:
                    result.error = "Post created, but public access could not be verified."
                return result

        except httpx.TimeoutException:
            return self.failure("Bluesky API request timed out.")
        except httpx.RequestError as error:
            return self.failure(
                f"Bluesky network error: {type(error).__name__}"
            )
        except (ValueError, TypeError):
            return self.failure(
                "Bluesky returned an invalid response."
            )
