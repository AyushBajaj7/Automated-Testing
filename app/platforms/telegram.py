import httpx
from datetime import datetime, timezone
from app.config import settings
from app.platforms.base import BasePlatform, PlatformResult


class TelegramPlatform(BasePlatform):
    name = "Telegram"

    async def publish(self, message: str) -> PlatformResult:
        if (
            not settings.TELEGRAM_BOT_TOKEN
            or not settings.TELEGRAM_CHAT_ID
        ):
            return self.failure(
                "Telegram credentials are not configured."
            )

        token = settings.TELEGRAM_BOT_TOKEN.strip()
        chat_id = settings.TELEGRAM_CHAT_ID.strip()
        endpoint = (
            f"https://api.telegram.org/bot{token}/sendMessage"
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    endpoint,
                    json={
                        "chat_id": chat_id,
                        "text": message,
                        "link_preview_options": {
                            "is_disabled": False
                        },
                    },
                )

                if not response.is_success:
                    return self.failure(
                        "Telegram API request failed: " + self.get_error(response)
                    )

                data = response.json()
                if not isinstance(data, dict) or not data.get("ok"):
                    return self.failure(
                        "Telegram rejected the message: "
                        + str(data.get("description", "Unknown error"))[:300]
                    )

                result = data.get("result")
                if not isinstance(result, dict):
                    return self.failure(
                        "Invalid Telegram response."
                    )

                message_id = result.get("message_id")
                chat = result.get("chat", {})

                if not message_id or not isinstance(chat, dict):
                    return self.failure(
                        "Telegram did not return message details."
                    )

                username = chat.get("username")
                chat_type = chat.get("type")
                posted_url = None
                public_access = False

                if username and chat_type == "channel":
                    posted_url = (
                        f"https://t.me/{username}/{message_id}"
                    )
                    # Conclusive public verification via Telegram public embed widget check
                    public_access = False
                    try:
                        embed_url = f"https://t.me/{username}/{message_id}?embed=1"
                        verify_resp = await client.get(
                            embed_url,
                            follow_redirects=True,
                            timeout=10.0,
                        )
                        if getattr(verify_resp, "is_success", False) is True:
                            html = str(getattr(verify_resp, "text", ""))
                            if "tgme_widget_message_error" in html or "Post not found" in html:
                                public_access = False
                            elif "tgme_widget_message" in html or "data-post" in html:
                                public_access = True
                            else:
                                public_access = False
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

                posted_date = result.get("date")
                if isinstance(posted_date, int):
                    created_at = datetime.fromtimestamp(
                        posted_date, timezone.utc
                    )
                    return PlatformResult(
                        platform=self.name,
                        status="success",
                        posted_url=posted_url,
                        public_access=public_access,
                        date=created_at.strftime("%Y-%m-%d"),
                        time=created_at.strftime("%H:%M:%S"),
                        error=(
                            None
                            if public_access
                            else (
                                "Message sent, but a public channel URL "
                                "could not be generated."
                            )
                        ),
                    )

                return self.success(
                    url=posted_url, public_access=public_access
                )

        except httpx.TimeoutException:
            return self.failure(
                "Telegram API request timed out."
            )
        except httpx.RequestError as error:
            return self.failure(
                f"Telegram network error: {type(error).__name__}"
            )
        except (ValueError, TypeError, OverflowError):
            return self.failure(
                "Telegram returned an invalid response."
            )
