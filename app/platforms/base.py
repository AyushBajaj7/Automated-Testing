from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Literal
import httpx
from pydantic import BaseModel


class PlatformResult(BaseModel):
    platform: str
    status: Literal["success", "failed"]
    posted_url: str | None = None
    public_access: bool = False
    date: str | None = None
    time: str | None = None
    error: str | None = None


class BasePlatform(ABC):
    name = "Unknown"

    @abstractmethod
    async def publish(self, message: str) -> PlatformResult:
        pass

    async def verify_public_access(self, client, url: str) -> bool:
        if not url or not url.startswith("https://"):
            return False
        try:
            response = await client.get(
                url,
                follow_redirects=True,
                timeout=10.0
            )
            return response.status_code == 200
        except (httpx.TimeoutException, httpx.RequestError):
            return False

    def success(
        self, url: str | None, public_access: bool = True
    ) -> PlatformResult:
        now = datetime.now(timezone.utc)
        return PlatformResult(
            platform=self.name,
            status="success",
            posted_url=url,
            public_access=public_access,
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            error=None,
        )

    def failure(self, error: str) -> PlatformResult:
        return PlatformResult(
            platform=self.name,
            status="failed",
            posted_url=None,
            public_access=False,
            date=None,
            time=None,
            error=error,
        )

    @staticmethod
    def get_error(response) -> str:
        try:
            data = response.json()
            error = (
                data.get("message")
                or data.get("error")
                or data.get("description")
            )
            if error:
                return str(error)[:300]
        except ValueError:
            pass
        return response.text[:300] or "Unknown API error"
