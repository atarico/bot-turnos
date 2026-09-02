"""Where the service account key comes from, and what happens when it is missing.

A container is rebuilt on every deploy and has no disk worth writing to, so
hosting platforms hand secrets over as environment variables. The file path
stays for local development, where a file is simply easier to handle.

The refusal below is the point of this module: a business that declares a real
calendar and silently books into an in-memory fake is the worst outcome
available, because everything looks like it worked.
"""

from __future__ import annotations

import json

import pytest

from bot.adapters import google_api
from bot.adapters.calendar_fake import FakeCalendar
from bot.adapters.google_calendar import GoogleCalendar
from bot.main import MisconfiguredTenant, build_calendar, google_credentials

from .conftest import build_bot

CALENDAR_ID = "peluqueria@group.calendar.google.com"
KEY = {"type": "service_account", "client_email": "turnos-bot@example.iam.gserviceaccount.com"}


@pytest.fixture
def config():
    return build_bot()[0].config


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch):
    """The developer's own environment must not decide what these tests prove."""
    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)


def _never_called(*args, **kwargs):
    raise AssertionError("the other credential source should have been used")


# -- picking a source ------------------------------------------------------


def test_nothing_configured_means_no_credentials():
    assert google_credentials() is None


def test_the_json_variable_wins_over_the_file_path(monkeypatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", json.dumps(KEY))
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/leftover/service-account.json")
    monkeypatch.setattr(google_api, "service_account_credentials_from_json", lambda raw: ("json", raw))
    monkeypatch.setattr(google_api, "service_account_credentials", _never_called)

    source, raw = google_credentials()

    assert source == "json"
    assert json.loads(raw) == KEY


def test_the_file_path_is_used_when_no_json_is_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "service-account.json")
    monkeypatch.setattr(google_api, "service_account_credentials", lambda path: ("file", path))
    monkeypatch.setattr(google_api, "service_account_credentials_from_json", _never_called)

    assert google_credentials() == ("file", "service-account.json")


def test_a_blank_variable_counts_as_unset(monkeypatch):
    """Platforms happily store an empty string, and an empty key is not a key."""
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "")

    assert google_credentials() is None


# -- wiring a tenant's calendar -------------------------------------------


def test_a_business_without_a_calendar_id_runs_on_the_fake(config):
    assert isinstance(build_calendar(config, None, credentials="creds"), FakeCalendar)


def test_a_declared_calendar_without_credentials_refuses_to_start(config):
    with pytest.raises(MisconfiguredTenant):
        build_calendar(config, CALENDAR_ID, credentials=None)


def test_the_refusal_never_repeats_the_credential(config, monkeypatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", json.dumps(KEY))

    with pytest.raises(MisconfiguredTenant) as raised:
        build_calendar(config, CALENDAR_ID, credentials=None)

    assert KEY["client_email"] not in str(raised.value)


def test_a_declared_calendar_with_credentials_talks_to_google(config, monkeypatch):
    monkeypatch.setattr(google_api, "GoogleCalendarApi", lambda credentials: ("api", credentials))

    calendar = build_calendar(config, CALENDAR_ID, credentials="creds")

    assert isinstance(calendar, GoogleCalendar)
