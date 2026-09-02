"""Per-customer conversation state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    CHOOSING_SERVICE = "choosing_service"
    CHOOSING_DAY = "choosing_day"
    CHOOSING_TIME = "choosing_time"
    CONFIRMING = "confirming"
    CHOOSING_CANCEL = "choosing_cancel"
    CONFIRMING_CANCEL = "confirming_cancel"


@dataclass
class Session:
    phone: str
    state: State = State.IDLE
    service_id: str | None = None
    day: date | None = None
    slot_start: datetime | None = None
    appointment_id: str | None = None
    page: int = 0
    """Cursor for whichever list is currently on screen."""

    def go(self, state: State) -> None:
        self.state = state
        self.page = 0

    def reset(self) -> None:
        self.state = State.IDLE
        self.service_id = None
        self.day = None
        self.slot_start = None
        self.appointment_id = None
        self.page = 0
