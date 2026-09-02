"""Ports. Everything the domain needs from the outside world, and nothing else.

Swapping FakeCalendar for GoogleCalendar, or SimulatorChannel for the real
Graph API, must not require touching a single line of bot.py.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from .config import Service
from .messages import OutgoingMessage
from .models import Appointment, Slot
from .session import Session


class CalendarPort(Protocol):
    def available_slots(self, service: Service, day: date) -> list[Slot]: ...

    def book(self, slot: Slot, customer_phone: str, customer_name: str) -> Appointment: ...

    def appointments_for(self, customer_phone: str) -> list[Appointment]: ...

    def cancel(self, appointment_id: str) -> None: ...


class ChannelPort(Protocol):
    def send(self, message: OutgoingMessage) -> None: ...


class SessionStorePort(Protocol):
    def get(self, phone: str) -> Session: ...

    def save(self, session: Session) -> None: ...
