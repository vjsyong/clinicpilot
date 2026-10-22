"""HTTP API router: health, chat, bookings, and authenticated page serving."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import bookings, chat, health, pages

router = APIRouter()
router.include_router(health.router)
router.include_router(chat.router)
router.include_router(bookings.router)
router.include_router(pages.router)
