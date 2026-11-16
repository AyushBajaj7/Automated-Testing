from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
import app.services.posting_service as posting_service
from app.main import app
from app.platforms.base import BasePlatform, PlatformResult

client = TestClient(app)


class FakePlatform:
    def __init__(self, name, should_fail=False, should_raise=False):
        self.name = name
        self.should_fail = should_fail
        self.should_raise = should_raise
        self.received_message = None

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

    async def publish(self, message: str) -> PlatformResult:
        self.received_message = message
        if self.should_raise:
            raise RuntimeError("Simulated platform error")
        if self.should_fail:
            return self.failure("Simulated publishing failure")

        now = datetime.now(timezone.utc)
        return PlatformResult(
            platform=self.name,
            status="success",
            posted_url=f"https://example.com/{self.name.lower()}",
            public_access=True,
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            error=None,
        )


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_valid_posting(monkeypatch):
    fake_platforms = [
        FakePlatform("Bluesky"),
        FakePlatform("Mastodon"),
        FakePlatform("DEV.to"),
        FakePlatform("WordPress"),
        FakePlatform("Telegram"),
    ]
    monkeypatch.setattr(posting_service, "PLATFORMS", fake_platforms)

    payload = {
        "message": "Check out our latest business platform. https://example.com"
    }
    response = client.post("/posting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total_platforms"] == 5
    assert data["successful"] == 5
    assert data["failed"] == 0
    assert len(data["results"]) == 5
    for r in data["results"]:
        assert r["status"] == "success"
        assert r["posted_url"] is not None
        assert r["public_access"] is True


def test_one_platform_failure(monkeypatch):
    fake_platforms = [
        FakePlatform("Bluesky"),
        FakePlatform("Mastodon", should_fail=True),
        FakePlatform("DEV.to"),
        FakePlatform("WordPress"),
        FakePlatform("Telegram"),
    ]
    monkeypatch.setattr(posting_service, "PLATFORMS", fake_platforms)

    payload = {
        "message": "Check out our latest business platform. https://example.com"
    }
    response = client.post("/posting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total_platforms"] == 5
    assert data["successful"] == 4
    assert data["failed"] == 1
    statuses = {r["platform"]: r["status"] for r in data["results"]}
    assert statuses["Mastodon"] == "failed"
    assert statuses["Bluesky"] == "success"


def test_unexpected_platform_error(monkeypatch):
    fake_platforms = [
        FakePlatform("Bluesky", should_raise=True),
        FakePlatform("Mastodon"),
        FakePlatform("DEV.to"),
        FakePlatform("WordPress"),
        FakePlatform("Telegram"),
    ]
    monkeypatch.setattr(posting_service, "PLATFORMS", fake_platforms)

    payload = {
        "message": "Check out our latest business platform. https://example.com"
    }
    response = client.post("/posting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total_platforms"] == 5
    assert data["successful"] == 4
    assert data["failed"] == 1
    bluesky_res = next(r for r in data["results"] if r["platform"] == "Bluesky")
    assert bluesky_res["status"] == "failed"
    assert "Unexpected error" in bluesky_res["error"]


def test_no_url_rejected():
    payload = {"message": "Check out our platform."}
    response = client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Message must contain exactly one URL." in response.text


def test_multiple_urls_rejected():
    payload = {"message": "Visit https://example.com and https://google.com"}
    response = client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Message must contain exactly one URL." in response.text


def test_message_over_200_characters_rejected():
    long_msg = "A" * 185 + " https://example.com"
    payload = {"message": long_msg}
    response = client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "String should have at most 200 characters" in response.text


def test_extra_platform_field_rejected():
    payload = {
        "message": "Visit our website https://example.com",
        "platforms": ["telegram"],
    }
    response = client.post("/posting", json=payload)
    assert response.status_code == 422
    assert "Extra inputs are not permitted" in response.text


def test_all_platforms_failure(monkeypatch):
    fake_platforms = [
        FakePlatform("Bluesky", should_fail=True),
        FakePlatform("Mastodon", should_fail=True),
        FakePlatform("DEV.to", should_fail=True),
        FakePlatform("WordPress", should_fail=True),
        FakePlatform("Telegram", should_fail=True),
    ]
    monkeypatch.setattr(posting_service, "PLATFORMS", fake_platforms)

    payload = {
        "message": "Check out our latest business platform. https://example.com"
    }
    response = client.post("/posting", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["total_platforms"] == 5
    assert data["successful"] == 0
    assert data["failed"] == 5
    for r in data["results"]:
        assert r["status"] == "failed"


@pytest.mark.asyncio
async def test_public_url_verification():
    class TestPlatform(BasePlatform):
        name = "Test"
        async def publish(self, message):
            return self.success(None, False)

    platform = TestPlatform()
    mock_client = type("FakeClient", (), {})()
    mock_client.get = AsyncMock(
        return_value=type("Response", (), {"status_code": 200})()
    )
    result = await platform.verify_public_access(
        mock_client,
        "https://example.com/post/123"
    )
    assert result is True

    mock_client.get = AsyncMock(
        return_value=type("Response", (), {"status_code": 404})()
    )
    result = await platform.verify_public_access(
        mock_client,
        "https://example.com/post/123"
    )
    assert result is False
