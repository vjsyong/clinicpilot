"""Process-local provider credentials.

The shared demo intentionally keeps the optional DeepSeek key in memory only:
it is never written to the database, the environment, or logs, and it is never
returned to the browser. A process restart therefore requires re-entering it.
"""

from __future__ import annotations

import threading

_MAX_KEY_CHARS = 512


class ProviderSettings:
    def __init__(self, *, initial_key: str = "") -> None:
        self._lock = threading.Lock()
        self._deepseek_key = initial_key.strip()

    def configured(self) -> bool:
        with self._lock:
            return bool(self._deepseek_key)

    def get_key(self) -> str:
        with self._lock:
            return self._deepseek_key

    def set_key(self, key: str) -> None:
        cleaned = key.strip()
        if not cleaned:
            raise ValueError("The API key must not be empty.")
        if len(cleaned) > _MAX_KEY_CHARS:
            raise ValueError("The API key is too long.")
        with self._lock:
            self._deepseek_key = cleaned

    def clear(self) -> None:
        with self._lock:
            self._deepseek_key = ""

    def masked_hint(self) -> str | None:
        with self._lock:
            if not self._deepseek_key:
                return None
            suffix = self._deepseek_key[-4:]
        return f"••••{suffix}"
