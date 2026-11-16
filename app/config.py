import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME = os.getenv(
        "APP_NAME", "Automated Multi-Platform Posting API"
    )
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "4000"))

    BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
    BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")
    BLUESKY_PDS_URL = os.getenv(
        "BLUESKY_PDS_URL", "https://bsky.social"
    )

    MASTODON_BASE_URL = os.getenv("MASTODON_BASE_URL", "")
    MASTODON_ACCESS_TOKEN = os.getenv("MASTODON_ACCESS_TOKEN", "")

    DEVTO_API_KEY = os.getenv("DEVTO_API_KEY", "")

    WORDPRESS_SITE_URL = os.getenv("WORDPRESS_SITE_URL", "")
    WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME", "")
    WORDPRESS_APP_PASSWORD = os.getenv(
        "WORDPRESS_APP_PASSWORD", ""
    )

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


settings = Settings()
