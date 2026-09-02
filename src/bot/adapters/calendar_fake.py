"""In-memory calendar: the stand-in for Google Calendar.

It answers the exact same port, so the Google adapter can replace it without
the conversation engine noticing. The one rule it must never break is the one
that matters in production: a slot is booked once, and only once.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Callable

from bot.domain.config import BusinessConfig, Service
from bot.domain.models import Appointment, Slot, SlotTaken


class FakeCalendar:
    def __init__(self, config: BusinessConfig, clock: Callable[[], datetime] | None = None) -> None:
        self.config = config
        self._clock = clock or (lambda: datetime.now(config.tz))
        self._appointments: dict[str, Appointment] = {}

    def available_slots(self, service: Service, day: date) -> list[Slot]:
        if day.weekday() in self.config.closed_weekdays:
            return []

        tz = self.config.tz
        now = self._clock()
        opening = datetime.combine(day, time(self.config.open_hour), tzinfo=tz)
        closing = datetime.combine(day, time(self.config.close_hour), tzinfo=tz)
        step = timedelta(minutes=self.config.slot_step_minutes)
        duration = timedelta(minutes=service.duration_minutes)

        slots: list[Slot] = []
        cursor = opening
        while cursor + duration <= closing:
            slot = Slot(start=cursor, service=service)
            if cursor > now and not self._is_busy(slot):
                slots.append(slot)
            cursor += step
        return slots

    def book(self, slot: Slot, customer_phone: str, customer_name: str) -> Appointment:
        if self._is_busy(slot):
            raise SlotTaken(slot.start.isoformat())
        appointment = Appointment(
            id=uuid.uuid4().hex[:12],
            customer_phone=customer_phone,
            customer_name=customer_name,
            slot=slot,
        )
        self._appointments[appointment.id] = appointment
        return appointment

    def appointments_for(self, customer_phone: str) -> list[Appointment]:
        now = self._clock()
        return sorted(
            (
                a
                for a in self._appointments.values()
                if a.customer_phone == customer_phone and a.slot.end > now
            ),
            key=lambda a: a.slot.start,
        )

    def cancel(self, appointment_id: str) -> None:
        self._appointments.pop(appointment_id, None)

    def _is_busy(self, slot: Slot) -> bool:
        return any(slot.overlaps(a.slot) for a in self._appointments.values())
