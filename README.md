# Automated Multi-Platform Posting System

A Python-based application that automatically publishes a single message across multiple third-party platforms using their official APIs.

The application provides a centralized REST API built with FastAPI. It validates incoming messages, executes platform integrations concurrently, handles individual failures independently, and returns a consolidated publishing report.

## Features

- Single API endpoint for multi-platform publishing.
- Maximum message length of 200 characters.
- Exactly one valid CTA URL required.
- Five third-party platform integrations.
- Concurrent publishing using Python asyncio.
- Independent error handling for each platform.
- Individual publishing status and post URL.
- Environment-based credential management.
- Interactive API documentation using Swagger.
- Automated testing using Pytest.

## Integrated Platforms

| Platform | Integration | Authentication |
|---|---|---|
| Bluesky | AT Protocol | App Password |
| Mastodon | REST API | Access Token |
| DEV.to | Forem API | API Key |
| WordPress | REST API | Application Password |
| Telegram | Bot API | Bot Token |

### Platform Behaviour

- Bluesky: Publishes a text post with a clickable URL.
- Mastodon: Publishes a public status.
- DEV.to: Creates and publishes an article with an automatically generated title.
- WordPress: Creates a published post with an automatically generated title.
- Telegram: Sends the message to a configured public channel.

Note: DEV.to and WordPress publish article/post formats rather than short-form social statuses.

## Technology Stack

- Python 3
- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- Python-dotenv
- Pytest

## Project Structure

```text
automated-posting/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── schemas.py
│   ├── config.py
│   │
│   ├── platforms/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── bluesky.py
│   │   ├── mastodon.py
│   │   ├── devto.py
│   │   ├── wordpress.py
│   │   └── telegram.py
│   │
│   └── services/
│       ├── __init__.py
│       └── posting_service.py
│
├── scripts/
│   ├── __init__.py
│   └── live_test.py
│
├── tests/
│   └── test_posting.py
│
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Installation and Setup

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd automated-posting
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Activate on Linux/macOS:

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root using `.env.example` as the template.

Configure the following credentials:

```env
APP_NAME=Automated Multi-Platform Posting API
HOST=0.0.0.0
PORT=4000

BLUESKY_HANDLE=
BLUESKY_APP_PASSWORD=
BLUESKY_PDS_URL=https://bsky.social

MASTODON_BASE_URL=
MASTODON_ACCESS_TOKEN=

DEVTO_API_KEY=

WORDPRESS_SITE_URL=
WORDPRESS_USERNAME=
WORDPRESS_APP_PASSWORD=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

LIVE_TEST_MESSAGE=
```

All API credentials must be configured before attempting live publishing.

Never upload `.env` to GitHub.

## Running the Application

Start the FastAPI server:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 4000
```

The application runs at:

http://localhost:4000

Interactive API documentation:

http://localhost:4000/docs

## API Documentation

### POST /posting

Accepts a message and automatically publishes it across all configured platforms.

#### Request Body

```json
{
  "message": "Check out our latest business platform and grow your online visibility. https://example.com"
}
```

#### Input Validation

- Message must not exceed 200 characters.
- Exactly one URL must be included.
- URL must use HTTP or HTTPS.
- Empty messages are rejected.
- Additional request fields are rejected.
- Platform selection is managed internally.

#### Response Structure

```json
{
  "success": true,
  "total_platforms": 5,
  "successful": 4,
  "failed": 1,
  "results": [
    {
      "platform": "Bluesky",
      "status": "success",
      "posted_url": "https://bsky.app/profile/example.com/post/123",
      "public_access": true,
      "date": "2026-11-17",
      "time": "10:30:00",
      "error": null
    },
    {
      "platform": "Mastodon",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Authentication failed"
    }
  ]
}
```

The above is an illustrative response. Actual results depend on the platform API responses.

The overall success field is true when at least one platform successfully publishes the message. Individual platform failures do not stop other integrations.

### Other Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | / | Application information |
| GET | /health | Health check |
| POST | /posting | Multi-platform publishing |

## Testing

### Run automated tests

```bash
python -m pytest tests/test_posting.py -v
```

Run the complete test suite:

```bash
python -m pytest -v
```

Check Python syntax:

```bash
python -m compileall app tests scripts
```

### Live platform testing

The live testing script allows individual platform integrations to be tested.

Example:

```bash
python -m scripts.live_test bluesky --confirm-public-post
```

Supported platforms:

- bluesky
- mastodon
- devto
- wordpress
- telegram

Live tests create actual posts. Use appropriate test content and verify the published results.

## Error Handling

The application handles:

- Missing API credentials.
- Authentication failures.
- Invalid API responses.
- Network errors.
- Request timeouts.
- Individual platform publishing failures.
- Unexpected exceptions.
- Public URL verification through unauthenticated HTTP requests.
- Separate tracking of publishing success and public accessibility.
- Reporting when a post is published but public access cannot be verified.

Each platform returns an independent result, allowing the remaining integrations to continue even when one platform encounters an error.

## Algorithms & Resilience Architecture

The service incorporates distributed systems patterns to enhance reliability and resource efficiency:

1. **Scatter-Gather Concurrency**: Broadcasts to all five platforms concurrently via `asyncio.gather`, bounding request latency to $\mathcal{O}(\max(T_1, \dots, T_5))$.
2. **Circuit Breaker State Machine (`CLOSED` / `OPEN` / `HALF_OPEN`)**: Trips after consecutive platform outages to fast-fail in $\mathcal{O}(1)$ time without wasting socket connections or incurring 30s timeouts. Only permits a single canary request during `HALF_OPEN` recovery.
3. **Exponential Backoff with Full Jitter**: Provides randomized backoff utility to mitigate the thundering herd problem against rate-limited endpoints.
4. **Bounded Concurrency Limiter (`asyncio.Semaphore`)**: Throttles active outbound sockets to prevent OS file descriptor exhaustion (`EMFILE`) under high burst traffic.
5. **Bandwidth-Optimized Public Probe (HTTP `HEAD` with `GET` Fallback)**: Attempts lightweight HTTP `HEAD` requests before falling back to `GET` to verify public permalinks without downloading full page bodies.
6. **Conclusive Public Verification**: Queries unauthenticated public API endpoints (Mastodon `/api/v1/statuses/{id}`, DEV.to `/api/articles/{id}`, WordPress `/wp/v2/posts/{id}`) where available to prevent false-positive login redirects.
7. **UTF-8 Byte-Offset Calculation**: Computes exact byte indices for Bluesky AT Protocol rich text facets, ensuring multi-byte Unicode and emoji characters are accurately linked.

## Security

- Credentials are stored using environment variables.
- `.env` is excluded through `.gitignore`.
- Application passwords and API tokens are not hardcoded.
- HTTPS is required for platform endpoints.
- Input validation is performed using Pydantic.
- Error responses avoid exposing stored credentials.

## Official API References

- Bluesky: https://docs.bsky.app/
- Mastodon: https://docs.joinmastodon.org/
- DEV.to: https://developers.forem.com/api/v1
- WordPress: https://developer.wordpress.org/rest-api/
- Telegram: https://core.telegram.org/bots/api

## Future Improvements

- Retry mechanisms with exponential backoff.
- Better independent public-access verification.
- Persistent publishing history.
- Idempotency and duplicate-post prevention.
- Structured application logging.
- Posting analytics and reporting.
- Additional social media integrations.

## Author

Developed as a Python practical assignment demonstrating REST API development, third-party API integration, asynchronous programming, validation, and error handling.
