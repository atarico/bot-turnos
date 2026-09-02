"""The real Google Calendar HTTP client.

Isolated from `google_calendar.py` on purpose: the booking rules are tested
without touching the network, and this file holds nothing but translation
between Google's JSON and RemoteEvent.

Auth is a service account. The business shares its calendar with the service
account's email and grants "Make changes to events" -- one step, no OAuth
consent screen, no Google app verification, no refresh tokens to rotate.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

from bot.adapters.google_calendar import RemoteEvent

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarUnavailable(RuntimeError):
    """The calendar could not be read. Never offer slots when this happens."""


def service_account_credentials(key_file: str):
    return service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)


def service_account_credentials_from_json(raw: str):
    """The same key, held in memory instead of on disk.

    Hosting platforms keep secrets in an encrypted store and expose them as
    environment variables. Writing that variable out to a temporary file first
    would only widen the window in which the key can be read.
    """
    return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)


class GoogleCalendarApi:
    def __init__(self, credentials) -> None:
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def busy(self, calendar_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        response = (
            self._service.freebusy()
            .query(
                body={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "items": [{"id": calendar_id}],
                }
            )
            .execute()
        )
        calendar = response.get("calendars", {}).get(calendar_id, {})
        if calendar.get("errors"):
            # Reading failed. Returning "nothing is busy" would hand out slots
            # that are already taken, so refuse instead.
            raise CalendarUnavailable(str(calendar["errors"]))
        return [(_parse(b["start"]), _parse(b["end"])) for b in calendar.get("busy", [])]

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
        created = (
            self._service.events()
            .insert(
                calendarId=calendar_id,
                body={
                    "summary": summary,
                    "description": description,
                    "start": {"dateTime": start.isoformat()},
                    "end": {"dateTime": end.isoformat()},
                    "extendedProperties": {"private": private_properties},
                },
            )
            .execute()
        )
        return _to_remote_event(created)

    def search(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
        private_property: tuple[str, str] | None = None,
    ) -> list[RemoteEvent]:
        params: dict = {
            "calendarId": calendar_id,
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": True,  # expand recurring events into real occurrences
            "orderBy": "startTime",
            "maxResults": 250,
        }
        if private_property is not None:
            params["privateExtendedProperty"] = f"{private_property[0]}={private_property[1]}"

        response = self._service.events().list(**params).execute()
        return [
            _to_remote_event(item)
            for item in response.get("items", [])
            # All-day events carry "date" instead of "dateTime"; they are blocks,
            # never appointments.
            if "dateTime" in item.get("start", {})
        ]

    def delete(self, calendar_id: str, event_id: str) -> None:
        try:
            self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        except HttpError as error:
            if error.status_code in (404, 410):
                return  # already gone, which is the outcome we wanted
            raise


def _to_remote_event(item: dict) -> RemoteEvent:
    return RemoteEvent(
        id=item["id"],
        start=_parse(item["start"]["dateTime"]),
        end=_parse(item["end"]["dateTime"]),
        private_properties=item.get("extendedProperties", {}).get("private", {}),
        created=_parse(item["created"]) if item.get("created") else None,
    )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
