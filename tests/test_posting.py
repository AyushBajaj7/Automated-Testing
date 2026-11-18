from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
import httpx
import pytest
from fastapi.testclient import TestClient

import app.services.posting_service as posting_service
from app.config import settings
from app.main import app
from app.platforms.base import BasePlatform, PlatformResult
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.wordpress import WordPressPlatform
from app.platforms.telegram import TelegramPlatform

client = TestClient(app)


# ============================================================================
# Section A: Fast Fake Platforms for Service & Endpoint Tests
# ============================================================================

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


# ============================================================================
# Section B: Mocked Connector Unit Tests (Testing Real Platform Payloads & APIs)
# ============================================================================

@pytest.mark.asyncio
async def test_bluesky_connector_mocked_success(monkeypatch):
    monkeypatch.setattr(settings, "BLUESKY_HANDLE", "alice.bsky.social")
    monkeypatch.setattr(settings, "BLUESKY_APP_PASSWORD", "app_pass_123")
    monkeypatch.setattr(settings, "BLUESKY_PDS_URL", "https://bsky.social")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        async def mock_post(url, **kwargs):
            if "createSession" in url:
                assert kwargs["json"]["identifier"] == "alice.bsky.social"
                return httpx.Response(200, json={"accessJwt": "jwt123", "did": "did:plc:alice"})
            elif "createRecord" in url:
                assert "Bearer jwt123" in kwargs["headers"]["Authorization"]
                return httpx.Response(200, json={"uri": "at://did:plc:alice/app.bsky.feed.post/3l7test"})
            return httpx.Response(404)

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.get = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"uri": "at://did:plc:alice/app.bsky.feed.post/3l7test"},
            )
        )
        mock_client.head = AsyncMock(return_value=httpx.Response(200))

        platform = BlueskyPlatform()
        result = await platform.publish("Check out our tool! https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://bsky.app/profile/alice.bsky.social/post/3l7test"
        assert result.public_access is True


@pytest.mark.asyncio
async def test_bluesky_connector_auth_failure(monkeypatch):
    monkeypatch.setattr(settings, "BLUESKY_HANDLE", "wrong.bsky.social")
    monkeypatch.setattr(settings, "BLUESKY_APP_PASSWORD", "bad_pass")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = httpx.Response(401, json={"message": "Invalid identifier or password"})

        platform = BlueskyPlatform()
        result = await platform.publish("Check out https://example.com")

        assert result.status == "failed"
        assert "Authentication failed" in result.error


@pytest.mark.asyncio
async def test_mastodon_connector_mocked_success(monkeypatch):
    monkeypatch.setattr(settings, "MASTODON_BASE_URL", "https://mastodon.social")
    monkeypatch.setattr(settings, "MASTODON_ACCESS_TOKEN", "bearer_token_123")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"id": "999888", "url": "https://mastodon.social/@user/999888", "visibility": "public"}
            )
        )
        mock_client.get = AsyncMock(
            return_value=httpx.Response(200, json={"id": "999888", "visibility": "public"})
        )

        platform = MastodonPlatform()
        result = await platform.publish("Public update https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://mastodon.social/@user/999888"
        assert result.public_access is True


@pytest.mark.asyncio
async def test_mastodon_connector_api_failure(monkeypatch):
    monkeypatch.setattr(settings, "MASTODON_BASE_URL", "https://mastodon.social")
    monkeypatch.setattr(settings, "MASTODON_ACCESS_TOKEN", "invalid_token")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = httpx.Response(401, json={"error": "The access token is invalid"})

        platform = MastodonPlatform()
        result = await platform.publish("Check out https://example.com")

        assert result.status == "failed"
        assert "Publishing failed" in result.error


@pytest.mark.asyncio
async def test_devto_connector_mocked_success(monkeypatch):
    monkeypatch.setattr(settings, "DEVTO_API_KEY", "devto_key_123")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        async def mock_post(url, **kwargs):
            assert kwargs["headers"]["api-key"] == "devto_key_123"
            assert kwargs["json"]["article"]["published"] is True
            return httpx.Response(201, json={"id": 12345, "url": "https://dev.to/user/post-slug", "published": True})

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.get = AsyncMock(return_value=httpx.Response(200, json={"published": True}))

        platform = DevToPlatform()
        result = await platform.publish("Exciting new framework release! https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://dev.to/user/post-slug"
        assert result.public_access is True


@pytest.mark.asyncio
async def test_devto_connector_api_failure(monkeypatch):
    monkeypatch.setattr(settings, "DEVTO_API_KEY", "invalid_key")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = httpx.Response(401, json={"error": "unauthorized"})

        platform = DevToPlatform()
        result = await platform.publish("Check this https://example.com")

        assert result.status == "failed"
        assert "Publishing failed" in result.error


@pytest.mark.asyncio
async def test_wordpress_connector_mocked_success(monkeypatch):
    monkeypatch.setattr(settings, "WORDPRESS_SITE_URL", "https://example.com")
    monkeypatch.setattr(settings, "WORDPRESS_USERNAME", "admin")
    monkeypatch.setattr(settings, "WORDPRESS_APP_PASSWORD", "abcd 1234 efgh")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        async def mock_post(url, **kwargs):
            assert kwargs["auth"] == ("admin", "abcd1234efgh")
            assert kwargs["json"]["status"] == "publish"
            return httpx.Response(201, json={"id": 42, "link": "https://example.com/blog/slug", "status": "publish"})

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.get = AsyncMock(return_value=httpx.Response(200, json={"status": "publish"}))

        platform = WordPressPlatform()
        result = await platform.publish("New blog post update https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://example.com/blog/slug"
        assert result.public_access is True


@pytest.mark.asyncio
async def test_wordpress_connector_api_failure(monkeypatch):
    monkeypatch.setattr(settings, "WORDPRESS_SITE_URL", "https://example.com")
    monkeypatch.setattr(settings, "WORDPRESS_USERNAME", "admin")
    monkeypatch.setattr(settings, "WORDPRESS_APP_PASSWORD", "wrong_pass")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = httpx.Response(403, json={"message": "Sorry, you are not allowed to create posts"})

        platform = WordPressPlatform()
        result = await platform.publish("Check this https://example.com")

        assert result.status == "failed"
        assert "Publishing failed" in result.error


@pytest.mark.asyncio
async def test_telegram_connector_mocked_success(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:BOT_TOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "@my_public_channel")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        async def mock_post(url, **kwargs):
            assert "123456:BOT_TOKEN" in url
            assert kwargs["json"]["chat_id"] == "@my_public_channel"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": 777,
                        "date": 1763337600,
                        "chat": {"username": "my_public_channel", "type": "channel"}
                    }
                }
            )

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.get = AsyncMock(
            return_value=httpx.Response(
                200,
                text='<div class="tgme_widget_message" data-post="my_public_channel/777"><div class="tgme_widget_message_text">Hello</div></div>',
            )
        )
        mock_client.head = AsyncMock(return_value=httpx.Response(200))

        platform = TelegramPlatform()
        result = await platform.publish("Check out our channel https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://t.me/my_public_channel/777"
        assert result.public_access is True


@pytest.mark.asyncio
async def test_telegram_connector_api_failure(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:BOT_TOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "@nonexistent_channel")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = httpx.Response(
            400,
            json={"ok": False, "description": "Bad Request: chat not found"}
        )

        platform = TelegramPlatform()
        result = await platform.publish("Check this https://example.com")

        assert result.status == "failed"
        assert "Telegram API request failed" in result.error or "Telegram rejected the message" in result.error


# ============================================================================
# Section C: Resilience & Algorithmic Unit Tests
# ============================================================================

def test_circuit_breaker_state_machine():
    from app.services.circuit_breaker import CircuitBreaker, CircuitState
    import time

    cb = CircuitBreaker("TestService", failure_threshold=2, recovery_timeout=0.1)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True

    # 1 failure -> stays closed
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True

    # 2nd failure -> trips to OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False

    # After recovery timeout -> transitions to HALF_OPEN on first call, blocks subsequent probes
    time.sleep(0.15)
    assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.can_execute() is False

    # Success in half open -> resets to CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_publish_with_retry_and_backoff_transient_failure():
    from app.services.posting_service import publish_with_retry_and_backoff

    attempts = 0

    class TransientFailPlatform(BasePlatform):
        name = "TransientTest"
        async def publish(self, message: str) -> PlatformResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.RequestError("Temporary network reset")
            return self.success(url="https://example.com/recovered", public_access=True)

    platform = TransientFailPlatform()
    res = await publish_with_retry_and_backoff(
        platform, "Test message https://example.com", max_retries=1, base_backoff=0.01
    )

    assert attempts == 2
    assert res.status == "success"
    assert res.posted_url == "https://example.com/recovered"


@pytest.mark.asyncio
async def test_circuit_breaker_fast_fail_in_posting_service():
    from app.services.posting_service import publish_safely, CIRCUIT_BREAKERS
    from app.services.circuit_breaker import CircuitBreaker, CircuitState

    cb = CircuitBreaker("FastFailTest", failure_threshold=1, recovery_timeout=60.0)
    cb.state = CircuitState.OPEN
    CIRCUIT_BREAKERS["FastFailTest"] = cb

    class BreakerPlatform(BasePlatform):
        name = "FastFailTest"
        async def publish(self, message: str) -> PlatformResult:
            return self.success("https://example.com/never-reached", True)

    platform = BreakerPlatform()
    result = await publish_safely(platform, "Check this https://example.com")

    assert result.status == "failed"
    assert "Circuit breaker is OPEN" in result.error


@pytest.mark.asyncio
async def test_circuit_breaker_transient_vs_permanent_classification():
    from app.services.posting_service import (
        is_transient_failure,
        publish_safely,
        CIRCUIT_BREAKERS,
    )
    from app.services.circuit_breaker import CircuitBreaker, CircuitState

    # 1. Pure classification unit checks
    # Permanent errors must NOT be transient
    assert is_transient_failure("Bluesky credentials are not configured.") is False
    assert is_transient_failure("Authentication failed: (HTTP 401) Unauthorized") is False
    assert is_transient_failure("Publishing failed: (HTTP 403) Forbidden") is False
    assert is_transient_failure("Publishing failed: (HTTP 400) Bad Request") is False
    assert is_transient_failure("WordPress site URL must not contain credentials.") is False
    assert is_transient_failure("Mastodon instance must use HTTPS.") is False

    # Transient infrastructure errors MUST be transient
    assert is_transient_failure("Bluesky API request timed out.") is True
    assert is_transient_failure("Bluesky network error: ConnectError") is True
    assert is_transient_failure("Publishing failed: (HTTP 500) Internal Server Error") is True
    assert is_transient_failure("Publishing failed: (HTTP 502) Bad Gateway") is True
    assert is_transient_failure("Publishing failed: (HTTP 503) Service Unavailable") is True
    assert is_transient_failure("Publishing failed: (HTTP 504) Gateway Timeout") is True
    assert is_transient_failure("Publishing failed: (HTTP 429) Too Many Requests") is True
    assert is_transient_failure("Unexpected error: RuntimeError") is True

    # 2. Integration with publish_safely: Permanent errors do NOT trip circuit breaker
    cb_perm = CircuitBreaker("PermService", failure_threshold=3, recovery_timeout=60.0)
    CIRCUIT_BREAKERS["PermService"] = cb_perm

    class PermFailPlatform(BasePlatform):
        name = "PermService"
        async def publish(self, message: str) -> PlatformResult:
            return self.failure("Authentication failed: (HTTP 401) Invalid API token")

    perm_plat = PermFailPlatform()
    for _ in range(5):
        res = await publish_safely(perm_plat, "Message https://example.com")
        assert res.status == "failed"

    # Circuit breaker remains CLOSED because 401 is a permanent client/credential error
    assert cb_perm.failure_count == 0
    assert cb_perm.state == CircuitState.CLOSED
    assert cb_perm.can_execute() is True

    # 3. Integration with publish_safely: Transient errors DO trip circuit breaker
    cb_trans = CircuitBreaker("TransService", failure_threshold=3, recovery_timeout=60.0)
    CIRCUIT_BREAKERS["TransService"] = cb_trans

    class TransFailPlatform(BasePlatform):
        name = "TransService"
        async def publish(self, message: str) -> PlatformResult:
            return self.failure("Publishing failed: (HTTP 503) Service Unavailable")

    trans_plat = TransFailPlatform()
    for i in range(3):
        res = await publish_safely(trans_plat, "Message https://example.com")
        assert res.status == "failed"

    # Circuit breaker trips to OPEN because 503 is a transient outage
    assert cb_trans.failure_count == 3
    assert cb_trans.state == CircuitState.OPEN
    assert cb_trans.can_execute() is False


@pytest.mark.asyncio
async def test_telegram_unauthenticated_public_verification_not_found(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:BOT_TOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "@my_public_channel")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": 999999,
                        "date": 1763337600,
                        "chat": {"username": "my_public_channel", "type": "channel"},
                    },
                },
            )
        )
        # Embed endpoint returns "Post not found" widget
        mock_client.get = AsyncMock(
            return_value=httpx.Response(
                200,
                text='<div class="tgme_widget_message_error" dir="auto">Post not found</div>',
            )
        )
        mock_client.head = AsyncMock(return_value=httpx.Response(404))

        platform = TelegramPlatform()
        result = await platform.publish("Check this out https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://t.me/my_public_channel/999999"
        assert result.public_access is False
        assert "Message sent, but a public channel URL could not be generated." in result.error


@pytest.mark.asyncio
async def test_bluesky_unauthenticated_public_verification_not_found(monkeypatch):
    monkeypatch.setattr(settings, "BLUESKY_HANDLE", "alice.bsky.social")
    monkeypatch.setattr(settings, "BLUESKY_APP_PASSWORD", "app_pass_123")
    monkeypatch.setattr(settings, "BLUESKY_PDS_URL", "https://bsky.social")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        async def mock_post(url, **kwargs):
            if "createSession" in url:
                return httpx.Response(200, json={"accessJwt": "jwt123", "did": "did:plc:alice"})
            elif "createRecord" in url:
                return httpx.Response(200, json={"uri": "at://did:plc:alice/app.bsky.feed.post/3l7test"})
            return httpx.Response(404)

        mock_client.post = AsyncMock(side_effect=mock_post)
        # Record lookup on PDS returns 400 RecordNotFound
        mock_client.get = AsyncMock(
            return_value=httpx.Response(400, json={"error": "RecordNotFound", "message": "Could not locate record"})
        )
        mock_client.head = AsyncMock(return_value=httpx.Response(404))

        platform = BlueskyPlatform()
        result = await platform.publish("Check out our tool! https://example.com")

        assert result.status == "success"
        assert result.posted_url == "https://bsky.app/profile/alice.bsky.social/post/3l7test"
        assert result.public_access is False
        assert "Post created, but public access could not be verified." in result.error
