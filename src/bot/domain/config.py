"""Business configuration: what is sold, when, and for how long."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    duration_minutes: int


@dataclass(frozen=True)
class BusinessConfig:
    name: str
    timezone: str
    services: tuple[Service, ...]
    open_hour: int = 9
    close_hour: int = 18
    slot_step_minutes: int = 30
    days_ahead: int = 7
    closed_weekdays: tuple[int, ...] = (6,)  # Monday is 0, so 6 is Sunday.

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def service(self, service_id: str) -> Service | None:
        return next((s for s in self.services if s.id == service_id), None)
