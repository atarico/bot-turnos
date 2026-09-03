"""Production wiring: many businesses, one process, driven by the environment.

The simulator (bot.simulator.app) is this same application with two adapters
swapped for fakes. That swap is the whole difference.

One service account key serves every tenant: each business shares its own
calendar with that same service account email. Access tokens are read from the
environment by name so no secret ever lands in the tenants file.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from bot.adapters.calendar_fake import FakeCalendar
from bot.adapters.channel_simulator import SimulatorChannel
from bot.adapters.channel_whatsapp import WhatsAppChannel
from bot.adapters.session_store import InMemorySessionStore
from bot.domain.bot import Bot
from bot.domain.config import BusinessConfig, Service
from bot.domain.ports import CalendarPort, ChannelPort
from bot.tenants import Tenant, TenantRegistry
from bot.webhook import create_app

logger = logging.getLogger(__name__)

CREDENTIALS_JSON = "GOOGLE_CREDENTIALS_JSON"  # the key itself, for hosted deploys
CREDENTIALS_FILE = "GOOGLE_CREDENTIALS_FILE"  # a path to it, for local development

TENANTS_JSON = "TENANTS_JSON"  # the businesses themselves, for hosted deploys
TENANTS_FILE = "TENANTS_FILE"  # a path to them, for local development


class MisconfiguredTenant(RuntimeError):
    """A business declares a real calendar and we hold no key to reach it.

    Refusing to start is the whole point. Falling back to the fake would book
    appointments into memory while every screen says the booking succeeded.
    """


def google_credentials():
    """Credentials for the one service account every tenant shares, or None.

    The key content wins over the path: a container is rebuilt on every deploy,
    so in production the key arrives as an environment variable and there is no
    file to point at.
    """
    raw = os.getenv(CREDENTIALS_JSON)
    if raw:
        from bot.adapters import google_api

        return google_api.service_account_credentials_from_json(raw)

    key_file = os.getenv(CREDENTIALS_FILE)
    if key_file:
        from bot.adapters import google_api

        return google_api.service_account_credentials(key_file)

    return None


def parse_business(raw: dict) -> BusinessConfig:
    raw = dict(raw)
    services = tuple(Service(**service) for service in raw.pop("services"))
    closed = raw.pop("closed_weekdays", None)
    return BusinessConfig(
        services=services,
        closed_weekdays=tuple(closed) if closed is not None else (6,),
        **raw,
    )


def build_calendar(config: BusinessConfig, calendar_id: str | None, *, credentials) -> CalendarPort:
    if not calendar_id:
        # No calendar declared: the demo business and the simulator live here.
        return FakeCalendar(config)

    if credentials is None:
        raise MisconfiguredTenant(
            f"{config.name} declares a Google calendar but no service account key was found. "
            f"Set {CREDENTIALS_JSON} (the key itself) or {CREDENTIALS_FILE} (a path to it)."
        )

    from bot.adapters import google_api
    from bot.adapters.google_calendar import GoogleCalendar

    return GoogleCalendar(
        config=config,
        api=google_api.GoogleCalendarApi(credentials),
        calendar_id=calendar_id,
    )


def build_channel(phone_number_id: str, access_token: str | None) -> ChannelPort:
    if not access_token:
        return SimulatorChannel()
    return WhatsAppChannel(access_token=access_token, phone_number_id=phone_number_id)


def build_tenant(entry: dict, *, credentials=None) -> Tenant:
    phone_number_id = entry["phone_number_id"]
    config = parse_business(entry["business"])
    calendar = build_calendar(config, entry.get("google_calendar_id"), credentials=credentials)
    return Tenant(
        id=phone_number_id,
        config=config,
        bot=Bot(config=config, calendar=calendar, sessions=InMemorySessionStore()),
        channel=build_channel(phone_number_id, os.getenv(entry.get("access_token_env", ""))),
    )


def tenants_document() -> dict | None:
    """The businesses to serve, or None to fall back to the demo.

    The content wins over the path, for the same reason the key does: a hosted
    container has nowhere to keep a file.
    """
    raw = os.getenv(TENANTS_JSON)
    if raw:
        return json.loads(raw)

    path = os.getenv(TENANTS_FILE)
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    return None


def build_registry() -> TenantRegistry:
    # Resolved once: one service account key serves every tenant.
    credentials = google_credentials()

    document = tenants_document()
    if document is None:
        from bot.simulator.app import DEMO_BUSINESS, DEMO_PHONE_NUMBER_ID

        logger.warning("%s and %s are unset; serving the demo business only", TENANTS_JSON, TENANTS_FILE)
        return TenantRegistry(
            [
                build_tenant(
                    {
                        "phone_number_id": DEMO_PHONE_NUMBER_ID,
                        "business": _as_dict(DEMO_BUSINESS),
                    },
                    credentials=credentials,
                )
            ]
        )

    return TenantRegistry(
        [build_tenant(entry, credentials=credentials) for entry in document["tenants"]]
    )


def _as_dict(config: BusinessConfig) -> dict:
    return {
        "name": config.name,
        "timezone": config.timezone,
        "open_hour": config.open_hour,
        "close_hour": config.close_hour,
        "slot_step_minutes": config.slot_step_minutes,
        "days_ahead": config.days_ahead,
        "closed_weekdays": list(config.closed_weekdays),
        "services": [
            {"id": s.id, "name": s.name, "duration_minutes": s.duration_minutes}
            for s in config.services
        ],
    }


def build_app():
    return create_app(
        registry=build_registry(),
        verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", "change-me"),
        app_secret=os.getenv("WHATSAPP_APP_SECRET") or None,
    )


app = build_app()
