"""The Google adapter, exercised against an in-memory stand-in for the API.

No network here on purpose: what needs testing is the booking logic, not
Google's HTTP client.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from bot.adapters.google_calendar import BOT_MARKER, GoogleCalendar, RemoteEvent
from bot.domain.config import BusinessConfig, Service
from bot.domain.models import Slot, SlotTaken

from .conftest import CUSTOMER, NOW, OTHER, TZ

CALENDAR_ID = "peluqueria@gmail.com"
CORTE = Service(id="corte", name="Corte", duration_minutes=30)


class FakeCalendarApi:
    """In-memory CalendarApi. `rival_on_insert` reproduces the race."""

    def __init__(self) -> None:
        self.events: dict[str, RemoteEvent] = {}
        self.deleted: list[str] = []
        self.rival_on_insert: RemoteEvent | None = None
        self._seq = 0

    def busy(self, calendar_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        return [
            (e.start, e.end)
            for e in self.events.values()
            if e.start < end and start < e.end
        ]

    def insert(
        self,
        calendar_id: str,
        *,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        private_properties: dict[str, str],
    ) -> RemoteEvent:
        # Somebody slipped in between our availability check and this insert.
        if self.rival_on_insert is not None:
            self.events[self.rival_on_insert.id] = self.rival_on_insert
            self.rival_on_insert = None

        self._seq += 1
        event = RemoteEvent(
            id=f"evt{self._seq}",
            start=start,
            end=end,
            private_properties=private_properties,
            created=NOW + timedelta(seconds=self._seq),
        )
        self.events[event.id] = event
        return event

    def search(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
        private_property: tuple[str, str] | None = None,
    ) -> list[RemoteEvent]:
        found = [e for e in self.events.values() if e.start < time_max and time_min < e.end]
        if private_property is not None:
            key, value = private_property
            found = [e for e in found if e.private_properties.get(key) == value]
        return sorted(found, key=lambda e: e.start)

    def delete(self, calendar_id: str, event_id: str) -> None:
        self.events.pop(event_id, None)
        self.deleted.append(event_id)


@pytest.fixture
def setup():
    config = BusinessConfig(
        name="Peluqueria Rivadavia",
        timezone="America/Argentina/Buenos_Aires",
        services=(CORTE,),
        open_hour=9,
        close_hour=13,
        slot_step_minutes=30,
        days_ahead=3,
    )
    api = FakeCalendarApi()
    calendar = GoogleCalendar(
        config=config,
        api=api,
        calendar_id=CALENDAR_ID,
        clock=lambda: NOW,
    )
    return calendar, api


def bot_event(start: datetime, minutes: int = 30, event_id: str = "rival", created_offset: int = -60) -> RemoteEvent:
    return RemoteEvent(
        id=event_id,
        start=start,
        end=start + timedelta(minutes=minutes),
        private_properties={BOT_MARKER: "1", "phone": OTHER, "service": "corte"},
        created=NOW + timedelta(seconds=created_offset),
    )


def test_free_day_offers_every_future_slot(setup):
    calendar, _ = setup

    slots = calendar.available_slots(CORTE, NOW.date())

    assert [s.start.strftime("%H:%M") for s in slots] == ["10:30", "11:00", "11:30", "12:00", "12:30"]


def test_a_busy_block_removes_the_overlapping_slots(setup):
    calendar, api = setup
    # The owner blocked 11:00-12:00 straight from their phone.
    api.events["own"] = RemoteEvent(
        id="own",
        start=datetime(2026, 9, 1, 11, 0, tzinfo=TZ),
        end=datetime(2026, 9, 1, 12, 0, tzinfo=TZ),
        private_properties={},
        created=NOW,
    )

    slots = calendar.available_slots(CORTE, NOW.date())

    assert [s.start.strftime("%H:%M") for s in slots] == ["10:30", "12:00", "12:30"]


def test_booking_writes_the_event_with_the_customer_attached(setup):
    calendar, api = setup
    slot = Slot(start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ), service=CORTE)

    appointment = calendar.book(slot, CUSTOMER, "Ana")

    stored = api.events[appointment.id]
    assert stored.private_properties["phone"] == CUSTOMER
    assert stored.private_properties["service"] == "corte"
    assert stored.private_properties[BOT_MARKER] == "1"
    assert stored.end - stored.start == timedelta(minutes=30)


def test_booking_an_already_busy_slot_is_refused(setup):
    calendar, api = setup
    api.events["taken"] = bot_event(datetime(2026, 9, 1, 10, 30, tzinfo=TZ))
    slot = Slot(start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ), service=CORTE)

    with pytest.raises(SlotTaken):
        calendar.book(slot, CUSTOMER, "Ana")


def test_losing_the_insert_race_rolls_our_event_back(setup):
    calendar, api = setup
    # Created before ours, so the rival wins the tie-break.
    api.rival_on_insert = bot_event(datetime(2026, 9, 1, 10, 30, tzinfo=TZ), created_offset=-1)
    slot = Slot(start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ), service=CORTE)

    with pytest.raises(SlotTaken):
        calendar.book(slot, CUSTOMER, "Ana")

    assert api.deleted, "our event must be rolled back after losing the race"
    assert not [e for e in api.events.values() if e.private_properties.get("phone") == CUSTOMER]
    assert "rival" in api.events


def test_winning_the_insert_race_keeps_our_event(setup):
    calendar, api = setup
    # Created after ours, so we win the tie-break and the rival is left alone.
    api.rival_on_insert = bot_event(datetime(2026, 9, 1, 10, 30, tzinfo=TZ), created_offset=999)
    slot = Slot(start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ), service=CORTE)

    appointment = calendar.book(slot, CUSTOMER, "Ana")

    assert appointment.id in api.events
    assert api.deleted == []


def test_appointments_are_looked_up_by_phone(setup):
    calendar, api = setup
    calendar.book(Slot(start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ), service=CORTE), CUSTOMER, "Ana")
    calendar.book(Slot(start=datetime(2026, 9, 1, 11, 30, tzinfo=TZ), service=CORTE), OTHER, "Bruno")

    mine = calendar.appointments_for(CUSTOMER)

    assert len(mine) == 1
    assert mine[0].customer_phone == CUSTOMER
    assert mine[0].slot.service.id == "corte"
    assert mine[0].slot.start == datetime(2026, 9, 1, 10, 30, tzinfo=TZ)


def test_events_the_business_created_by_hand_are_not_appointments(setup):
    calendar, api = setup
    api.events["manual"] = RemoteEvent(
        id="manual",
        start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ),
        end=datetime(2026, 9, 1, 11, 0, tzinfo=TZ),
        private_properties={},  # no bot marker, no phone
        created=NOW,
    )

    assert calendar.appointments_for(CUSTOMER) == []


def test_an_event_whose_service_no_longer_exists_is_skipped(setup):
    calendar, api = setup
    api.events["stale"] = RemoteEvent(
        id="stale",
        start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ),
        end=datetime(2026, 9, 1, 11, 0, tzinfo=TZ),
        private_properties={BOT_MARKER: "1", "phone": CUSTOMER, "service": "servicio-borrado"},
        created=NOW,
    )

    assert calendar.appointments_for(CUSTOMER) == []


def test_cancelling_deletes_the_event(setup):
    calendar, api = setup
    appointment = calendar.book(
        Slot(start=datetime(2026, 9, 1, 10, 30, tzinfo=TZ), service=CORTE), CUSTOMER, "Ana"
    )

    calendar.cancel(appointment.id)

    assert appointment.id not in api.events
    assert calendar.appointments_for(CUSTOMER) == []


def test_a_closed_day_offers_nothing(setup):
    calendar, _ = setup

    assert calendar.available_slots(CORTE, datetime(2026, 9, 6, tzinfo=TZ).date()) == []  # Sunday
