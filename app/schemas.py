import re
from ipaddress import ip_address
from urllib.parse import urlsplit
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator

URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+", re.IGNORECASE
)


class PostingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        ..., min_length=1, max_length=200
    )

    @field_validator("message", mode="before")
    @classmethod
    def clean_message(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("message")
    @classmethod
    def validate_message(cls, value):
        matches = URL_PATTERN.findall(value)
        if len(matches) != 1:
            raise ValueError(
                "Message must contain exactly one URL."
            )

        url = matches[0].rstrip(".,!?;:)]}")

        if any(char.isspace() for char in url):
            raise ValueError("URL cannot contain spaces.")

        parsed = urlsplit(url)

        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError("Only HTTP and HTTPS URLs are allowed.")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: hostname is missing.")

        try:
            ip_address(hostname)
        except ValueError:
            if "." not in hostname:
                raise ValueError("Invalid URL: hostname is not valid.")

        try:
            parsed.port
        except ValueError:
            raise ValueError("Invalid URL port.")

        if parsed.username or parsed.password:
            raise ValueError("URLs containing credentials are not allowed.")

        return value

    @property
    def extracted_url(self) -> str:
        """Helper to get the validated URL from the message."""
        matches = URL_PATTERN.findall(self.message)
        return matches[0].rstrip(".,!?;:)]}") if matches else ""


# Alias for compatibility
PostRequest = PostingRequest


# Platform result schemas for downstream steps
class PlatformResult(BaseModel):
    platform: str
    success: bool
    published_url: Optional[str] = None
    publicly_accessible: bool = False
    date: str
    time: str
    error: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class PostingSummary(BaseModel):
    total: int
    successful: int
    failed: int


class PostResponse(BaseModel):
    message: str
    cta_url: str
    timestamp: str
    summary: PostingSummary
    results: dict[str, PlatformResult]
