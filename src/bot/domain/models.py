"""Core appointment entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Service


class SlotTaken(Exception):
    """Raised when a slot was booked between being offered and being confirmed."""


@dataclass(frozen=True)
class Slot:
    start: datetime
    service: Service

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.service.duration_minutes)

    def overlaps(self, other: Slot) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Appointment:
    id: str
    customer_phone: str
    customer_name: str
    slot: Slot
