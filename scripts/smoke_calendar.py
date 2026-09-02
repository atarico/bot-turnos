"""Manual smoke test for the real Google Calendar connection.

Exercises the same `GoogleCalendarApi` the bot uses in production against a real
calendar: read availability, write an event, read it back, delete it. Anything
this script cannot do, the bot cannot do either.

    uv run python scripts/smoke_calendar.py peluqueria@gmail.com

The calendar id may also come from GOOGLE_CALENDAR_ID. The key file comes from
GOOGLE_CREDENTIALS_FILE (default: ./service-account.json).

The test event is created a day ahead, outside any plausible business hours, and
deleted before the script exits -- including when a step fails.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError

from bot.adapters.google_api import GoogleCalendarApi, service_account_credentials

MARKER = "smokeTest"
KEY_FILE_DEFAULT = "./service-account.json"


def fail(message: str, hint: str = "") -> None:
    print(f"  FAIL  {message}")
    if hint:
        print(f"\n{hint}\n")
    sys.exit(1)


def service_account_email(key_file: str) -> str:
    with open(key_file, encoding="utf-8") as handle:
        return json.load(handle).get("client_email", "<missing client_email>")


def explain(error: HttpError, calendar_id: str, email: str) -> str:
    if error.status_code == 404:
        return (
            f"Google says this calendar does not exist -- which is what it also says\n"
            f"when the calendar exists but was never shared with the service account.\n"
            f"That second case is the usual one.\n\n"
            f"Open Google Calendar as the owner of {calendar_id}, then:\n"
            f"  Settings for this calendar -> Share with specific people -> Add people\n"
            f"  Add: {email}\n"
            f"  Permission: Make changes to events"
        )
    if error.status_code == 403:
        return (
            f"Access denied. Two usual causes:\n"
            f"  1. The Google Calendar API is not enabled for this project.\n"
            f"     Console -> APIs & Services -> Library -> Google Calendar API -> Enable\n"
            f"  2. The calendar is shared with {email} as 'See only free/busy'.\n"
            f"     Reading works, writing does not. Raise it to 'Make changes to events'."
        )
    return str(error)


def main() -> None:
    calendar_id = (sys.argv[1] if len(sys.argv) > 1 else "") or os.getenv("GOOGLE_CALENDAR_ID", "")
    key_file = os.getenv("GOOGLE_CREDENTIALS_FILE", KEY_FILE_DEFAULT)

    if not calendar_id:
        fail(
            "no calendar id",
            "Pass it as an argument or set GOOGLE_CALENDAR_ID:\n"
            "  uv run python scripts/smoke_calendar.py peluqueria@gmail.com",
        )
    if not os.path.exists(key_file):
        fail(
            f"key file not found: {key_file}",
            "Download the service account JSON key from Google Cloud Console\n"
            "(IAM & Admin -> Service Accounts -> Keys -> Add Key -> JSON), or point\n"
            "GOOGLE_CREDENTIALS_FILE at wherever you saved it.",
        )

    email = service_account_email(key_file)
    print(f"\nservice account : {email}")
    print(f"calendar        : {calendar_id}\n")

    api = GoogleCalendarApi(service_account_credentials(key_file))

    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=3, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(minutes=15)
    event = None

    try:
        print("1/4  reading availability")
        busy = api.busy(calendar_id, start, start + timedelta(days=7))
        print(f"  OK    {len(busy)} busy block(s) in the next 7 days")

        print("2/4  writing a test event")
        event = api.insert(
            calendar_id,
            summary="[smoke test] delete me",
            description="Written by scripts/smoke_calendar.py. Deleted automatically.",
            start=start,
            end=end,
            private_properties={MARKER: "1"},
        )
        print(f"  OK    event {event.id} at {event.start.isoformat()}")

        print("3/4  reading it back by private property")
        found = api.search(
            calendar_id,
            time_min=start - timedelta(minutes=1),
            time_max=end + timedelta(minutes=1),
            private_property=(MARKER, "1"),
        )
        if not any(item.id == event.id for item in found):
            fail(
                "the event was written but did not come back in the search",
                "The booking race defense in google_calendar.py depends on this\n"
                "read-back. Without it, two customers can hold the same slot.",
            )
        print(f"  OK    found {len(found)} matching event(s)")

    except HttpError as error:
        fail(f"Google rejected the call ({error.status_code})", explain(error, calendar_id, email))
    finally:
        if event is not None:
            print("4/4  cleaning up")
            try:
                api.delete(calendar_id, event.id)
                print("  OK    test event deleted")
            except HttpError as error:
                print(f"  WARN  could not delete {event.id}: {error.status_code}")
                print(f"        remove it by hand from {calendar_id}")

    print("\nRead, write, read-back and delete all work. The bot is good to go.\n")


if __name__ == "__main__":
    main()
