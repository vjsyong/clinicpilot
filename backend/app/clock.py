from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FrozenClock:
    """Test clock. Advances only when explicitly moved."""

    current: datetime

    def now(self) -> datetime:
        if self.current.tzinfo is None:
            return self.current.replace(tzinfo=UTC)
        return self.current.astimezone(UTC)

    def advance(self, **kwargs: float) -> None:
        self.current = self.now() + timedelta(**kwargs)
