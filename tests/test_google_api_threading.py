"""One Google client per thread.

The webhook answers Meta immediately and does the real work in a background
thread, so several conversations reach the calendar at the same time. The
service object googleapiclient hands back keeps a dict of live connections with
no lock around it, so sharing one across threads means two of them writing into
the same TLS socket -- which surfaces as `SSLError: RECORD_LAYER_FAILURE` and
loses the appointment, silently, because the webhook only logs it.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.adapters import google_api

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
START = datetime(2026, 9, 1, 9, 0, tzinfo=TZ)
END = START + timedelta(days=1)
CALENDAR = "turnos-test@group.calendar.google.com"
THREADS = 8


class FakeService:
    """Enough of the discovery object for `busy()` to complete."""

    def freebusy(self):
        return self

    def query(self, body):
        return self

    def execute(self):
        return {"calendars": {CALENDAR: {"busy": []}}}


def record_builds(monkeypatch):
    built = []

    def fake_build(*args, **kwargs):
        service = FakeService()
        built.append(service)
        return service

    monkeypatch.setattr(google_api, "build", fake_build)
    return built


def test_overlapping_threads_each_get_their_own_client(monkeypatch):
    built = record_builds(monkeypatch)
    api = google_api.GoogleCalendarApi(credentials="creds")

    # The barrier is the point: every thread is inside the call at once, which
    # is exactly the situation a shared socket cannot survive.
    barrier = threading.Barrier(THREADS)
    failures: list[BaseException] = []

    def call():
        try:
            barrier.wait(timeout=10)
            api.busy(CALENDAR, START, END)
        except BaseException as error:  # noqa: BLE001 - reported below
            failures.append(error)

    threads = [threading.Thread(target=call) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not failures
    assert len(built) == THREADS
    assert len({id(service) for service in built}) == THREADS


def test_a_thread_reuses_the_client_it_already_built(monkeypatch):
    """Per-thread, not per-call: rebuilding on every message would be waste."""
    built = record_builds(monkeypatch)
    api = google_api.GoogleCalendarApi(credentials="creds")

    for _ in range(3):
        api.busy(CALENDAR, START, END)

    assert len(built) == 1
