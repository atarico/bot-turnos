"""The payoff of the port: the same conversation, a different calendar.

Not a single line of bot.py knows which one it is talking to.
"""

from __future__ import annotations

from datetime import datetime

from bot.adapters.google_calendar import GoogleCalendar
from bot.adapters.session_store import InMemorySessionStore
from bot.domain.bot import Bot
from bot.domain.config import BusinessConfig, Service
from bot.domain.messages import ButtonsMessage, ListMessage, TextMessage

from .conftest import CUSTOMER, NOW, OTHER, TZ, tap, txt
from .test_google_calendar import CORTE, FakeCalendarApi


def google_backed_bot() -> tuple[Bot, GoogleCalendar]:
    config = BusinessConfig(
        name="Peluqueria Rivadavia",
        timezone="America/Argentina/Buenos_Aires",
        services=(CORTE, Service(id="color", name="Color y peinado", duration_minutes=60)),
        open_hour=9,
        close_hour=13,
        slot_step_minutes=30,
        days_ahead=3,
    )
    calendar = GoogleCalendar(
        config=config,
        api=FakeCalendarApi(),
        calendar_id="peluqueria@gmail.com",
        clock=lambda: NOW,
    )
    bot = Bot(config=config, calendar=calendar, sessions=InMemorySessionStore(), clock=lambda: NOW)
    return bot, calendar


def test_the_whole_booking_flow_runs_on_google_calendar():
    bot, calendar = google_backed_bot()

    out = bot.handle(txt("hola"))
    assert isinstance(out[0], ButtonsMessage)

    out = bot.handle(tap("menu:book"))
    assert [r.id for r in out[0].rows] == ["svc:corte", "svc:color"]

    bot.handle(tap("svc:corte"))
    out = bot.handle(tap("day:2026-09-01"))
    assert [r.id for r in out[0].rows] == [
        "time:2026-09-01T10:30:00-03:00",
        "time:2026-09-01T11:00:00-03:00",
        "time:2026-09-01T11:30:00-03:00",
        "time:2026-09-01T12:00:00-03:00",
        "time:2026-09-01T12:30:00-03:00",
    ]

    bot.handle(tap("time:2026-09-01T10:30:00-03:00"))
    out = bot.handle(tap("confirm:yes"))

    assert isinstance(out[0], TextMessage)
    appointments = calendar.appointments_for(CUSTOMER)
    assert len(appointments) == 1
    assert appointments[0].slot.start == datetime(2026, 9, 1, 10, 30, tzinfo=TZ)


def test_a_slot_the_owner_blocked_by_hand_is_never_offered():
    bot, calendar = google_backed_bot()
    # The owner drops a dentist appointment into their own calendar at 11:00.
    calendar.api.insert(
        "peluqueria@gmail.com",
        summary="Dentista",
        description="",
        start=datetime(2026, 9, 1, 11, 0, tzinfo=TZ),
        end=datetime(2026, 9, 1, 12, 0, tzinfo=TZ),
        private_properties={},
    )

    bot.handle(txt("hola"))
    bot.handle(tap("menu:book"))
    bot.handle(tap("svc:corte"))
    out = bot.handle(tap("day:2026-09-01"))

    offered = [r.id for r in out[0].rows]
    assert "time:2026-09-01T11:00:00-03:00" not in offered
    assert "time:2026-09-01T11:30:00-03:00" not in offered
    assert "time:2026-09-01T10:30:00-03:00" in offered


def test_the_double_booking_guard_still_holds_on_google():
    bot, calendar = google_backed_bot()

    for phone in (CUSTOMER, OTHER):
        bot.handle(txt("hola", phone=phone))
        bot.handle(tap("menu:book", phone=phone))
        bot.handle(tap("svc:corte", phone=phone))
        bot.handle(tap("day:2026-09-01", phone=phone))
        bot.handle(tap("time:2026-09-01T10:30:00-03:00", phone=phone))

    bot.handle(tap("confirm:yes", phone=CUSTOMER))
    out = bot.handle(tap("confirm:yes", phone=OTHER))

    assert isinstance(out[0], TextMessage)
    assert "ya no esta disponible" in out[0].body.lower().replace("á", "a")
    assert len(calendar.appointments_for(CUSTOMER)) == 1
    assert calendar.appointments_for(OTHER) == []
