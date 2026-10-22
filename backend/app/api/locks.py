"""Per-conversation asyncio locks shared by blocking and streamed chat."""

from __future__ import annotations

import asyncio

from fastapi import Request


def conversation_lock(request: Request, conversation_id: str) -> asyncio.Lock:
    locks = getattr(request.app.state, "conversation_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        request.app.state.conversation_locks = locks
    lock = locks.get(conversation_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[conversation_id] = lock
    return lock
