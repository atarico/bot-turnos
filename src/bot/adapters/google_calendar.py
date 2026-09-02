"""Google Calendar behind CalendarPort.

The business's own calendar is the source of truth: whatever the owner blocks
from their phone disappears from what the bot offers, with no syncing involved.

The uncomfortable part, stated plainly: **Google Calendar has no atomic
"insert if free"**. Between asking for availability and writing the event,
somebody else can write the same slot. Both callers pass the check, both
insert, and the calendar happily holds two appointments at 10:30.

So booking is defended in three layers:

1. an in-process lock, which settles every race inside one worker;
2. a freebusy check inside that lock;
3. an optimistic read-back after the insert, which is the only thing that can
   catch a writer outside this process. Overlapping bot events are ordered by
   (created, id) and the loser deletes its own event and reports SlotTaken.

Layer 3 leaves a window of a few hundred milliseconds. Closing it completely
needs a lock the whole fleet shares (Redis) or an agenda we own. Until then,
never run more than one worker per calendar.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Protocol

from bot.domain.config import BusinessConfig, Service
from bot.domain.models import Appointment, Slot, SlotTaken

BOT_MARKER = "bookedByBot"
LOOKAHEAD_DAYS = 60


@dataclass(frozen=True)
class RemoteEvent:
    id: str
    start: datetime
    end: datetime
    private_properties: dict[str, str]
    created: datetime | None = None


class CalendarApi(Protocol):
    """The slice of Google Calendar this adapter needs. Keeps the HTTP client testable."""

    def busy(self, calendar_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]: ...

    def insert(
        self,
        calendar_id: str,
        *,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        private_properties: dict[str, str],
    ) -> RemoteEvent: ...

    def search(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
        private_property: tuple[str, str] | None = None,
    ) -> list[RemoteEvent]: ...

    def delete(self, calendar_id: str, event_id: str) -> None: ...


class GoogleCalendar:
    def __init__(
        self,
        *,
        config: BusinessConfig,
        api: CalendarApi,
        calendar_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.api = api
        self.calendar_id = calendar_id
        self._clock = clock or (lambda: datetime.now(config.tz))
        self._booking_lock = threading.Lock()

    # -- CalendarPort ------------------------------------------------------

    def available_slots(self, service: Service, day: date) -> list[Slot]:
        if day.weekday() in self.config.closed_weekdays:
            return []

        opening, closing = self._business_hours(day)
        busy = self.api.busy(self.calendar_id, opening, closing)
        now = self._clock()
        duration = timedelta(minutes=service.duration_minutes)
        step = timedelta(minutes=self.config.slot_step_minutes)

        slots: list[Slot] = []
        cursor = opening
        while cursor + duration <= closing:
            if cursor > now and not _overlaps_any(cursor, cursor + duration, busy):
                slots.append(Slot(start=cursor, service=service))
            cursor += step
        return slots

    def book(self, slot: Slot, customer_phone: str, customer_name: str) -> Appointment:
        properties = {
            BOT_MARKER: "1",
            "phone": customer_phone,
            "service": slot.service.id,
        }

        with self._booking_lock:
            if self.api.busy(self.calendar_id, slot.start, slot.end):
                raise SlotTaken(slot.start.isoformat())
            event = self.api.insert(
                self.calendar_id,
                summary=f"{slot.service.name} — {customer_name or customer_phone}",
                description=f"Reservado por WhatsApp\nTeléfono: {customer_phone}",
                start=slot.start,
                end=slot.end,
                private_properties=properties,
            )

        if not self._won_the_race(event, slot):
            self.api.delete(self.calendar_id, event.id)
            raise SlotTaken(slot.start.isoformat())

        return Appointment(
            id=event.id,
            customer_phone=customer_phone,
            customer_name=customer_name,
            slot=slot,
        )

    def appointments_for(self, customer_phone: str) -> list[Appointment]:
        now = self._clock()
        events = self.api.search(
            self.calendar_id,
            time_min=now,
            time_max=now + timedelta(days=LOOKAHEAD_DAYS),
            private_property=("phone", customer_phone),
        )

        appointments: list[Appointment] = []
        for event in events:
            if event.private_properties.get(BOT_MARKER) != "1":
                continue
            service = self.config.service(event.private_properties.get("service", ""))
            if service is None:
                # The business removed the service after the booking; nothing
                # sensible to show, and guessing a duration would be worse.
                continue
            appointments.append(
                Appointment(
                    id=event.id,
                    customer_phone=customer_phone,
                    customer_name=event.private_properties.get("name", ""),
                    slot=Slot(start=event.start, service=service),
                )
            )
        return sorted(appointments, key=lambda a: a.slot.start)

    def cancel(self, appointment_id: str) -> None:
        self.api.delete(self.calendar_id, appointment_id)

    # -- helpers -----------------------------------------------------------

    def _business_hours(self, day: date) -> tuple[datetime, datetime]:
        tz = self.config.tz
        return (
            datetime.combine(day, time(self.config.open_hour), tzinfo=tz),
            datetime.combine(day, time(self.config.close_hour), tzinfo=tz),
        )

    def _won_the_race(self, ours: RemoteEvent, slot: Slot) -> bool:
        """Deterministic tie-break: oldest event wins, id breaks a tie."""
        rivals = [
            event
            for event in self.api.search(
                self.calendar_id,
                time_min=slot.start,
                time_max=slot.end,
                private_property=(BOT_MARKER, "1"),
            )
            if event.start < slot.end and slot.start < event.end
        ]
        if not rivals:
            return True
        winner = min(rivals, key=_race_key)
        return winner.id == ours.id


def _race_key(event: RemoteEvent) -> tuple[datetime, str]:
    return (event.created or datetime.max.replace(tzinfo=None).astimezone(), event.id)


def _overlaps_any(start: datetime, end: datetime, blocks: list[tuple[datetime, datetime]]) -> bool:
    return any(start < block_end and block_start < end for block_start, block_end in blocks)
