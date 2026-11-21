"""Platform-neutral webhook event representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class NormalizedEvent:
    """Normalized event emitted by IG/Threads webhook adapters."""

    platform: str
    event_type: str
    object_id: str = ""
    actor_id: str = ""
    target_id: str = ""
    timestamp: str = ""
    text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.event_type}:{self.object_id}:{self.actor_id}:{self.timestamp}"
