"""HTTP API router: health, chat, bookings, and authenticated page serving."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    audit,
    bookings,
    chat,
    chat_stream,
    conversations,
    demo,
    health,
    knowledge,
    pages,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(chat.router)
router.include_router(chat_stream.router)
router.include_router(bookings.router)
router.include_router(conversations.router)
router.include_router(demo.router)
router.include_router(audit.router)
router.include_router(knowledge.router)
router.include_router(pages.router)
