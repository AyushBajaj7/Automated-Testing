from fastapi import FastAPI
from app.config import settings
from app.schemas import PostingRequest
from app.services.posting_service import (
    publish_message,
    PostingResponse
)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Automated multi-platform posting system"
)


@app.get("/")
async def home():
    return {
        "message": "Automated Posting API is running",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


@app.post("/posting", response_model=PostingResponse)
async def create_posting(request: PostingRequest):
    return await publish_message(request.message)
