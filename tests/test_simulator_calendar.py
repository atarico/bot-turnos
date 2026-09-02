"""The simulator, pointed at a real Google calendar.

The simulator's whole value is fidelity: it already drives the production
parser, de-duplication and state machine. The calendar was the last fake left,
and swapping it turns the simulator into a full rehearsal of production --
buttons, slots, double bookings and cancellations, all against Google -- with
nothing from Meta involved.

Fake stays the default. Booking into somebody's real calendar is something you
opt into, never something that happens because a variable leaked in.
"""

from __future__ import annotations

import pytest

from bot import main
from bot.adapters import google_api
from bot.adapters.calendar_fake import FakeCalendar
from bot.adapters.google_calendar import GoogleCalendar
from bot.main import MisconfiguredTenant
from bot.simulator import app as simulator

CALENDAR_ID = "turnos-test@group.calendar.google.com"


def calendar_of(app):
    return app.state.processor.registry.get(simulator.DEMO_PHONE_NUMBER_ID).bot.calendar


@pytest.fixture(autouse=True)
def no_ambient_calendar(monkeypatch):
    monkeypatch.delenv(simulator.CALENDAR_ID_ENV, raising=False)


def test_without_a_calendar_id_the_simulator_stays_on_the_fake():
    assert isinstance(calendar_of(simulator.build_app()), FakeCalendar)


def test_a_declared_calendar_sends_the_simulator_to_google(monkeypatch):
    monkeypatch.setenv(simulator.CALENDAR_ID_ENV, CALENDAR_ID)
    monkeypatch.setattr(main, "google_credentials", lambda: "creds")
    monkeypatch.setattr(google_api, "GoogleCalendarApi", lambda credentials: ("api", credentials))

    assert isinstance(calendar_of(simulator.build_app()), GoogleCalendar)


def test_a_declared_calendar_without_credentials_refuses_to_start(monkeypatch):
    """The same refusal production gets: never rehearse against a silent fake."""
    monkeypatch.setenv(simulator.CALENDAR_ID_ENV, CALENDAR_ID)
    monkeypatch.setattr(main, "google_credentials", lambda: None)

    with pytest.raises(MisconfiguredTenant):
        simulator.build_app()
