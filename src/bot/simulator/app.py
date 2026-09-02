"""Local simulator.

The point of this module is fidelity: /sim/send builds the exact envelope Meta
would POST and feeds it to the same WebhookProcessor the real webhook uses. The
parser, the de-duplication, the state machine and the calendar are all the
production ones. The only fake pieces are who delivers the message and where
the calendar lives -- which is exactly what we want to swap later.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from bot.adapters.channel_simulator import SimulatorChannel
from bot.adapters.session_store import InMemorySessionStore
from bot.domain.bot import Bot
from bot.domain.config import BusinessConfig, Service
from bot.tenants import Tenant, TenantRegistry
from bot.webhook import create_app

DEMO_BUSINESS = BusinessConfig(
    name="Peluquería Rivadavia",
    timezone="America/Argentina/Buenos_Aires",
    services=(
        Service(id="corte", name="Corte", duration_minutes=30),
        Service(id="color", name="Color y peinado", duration_minutes=60),
        Service(id="barba", name="Barba", duration_minutes=20),
    ),
    open_hour=9,
    close_hour=19,
    slot_step_minutes=30,
    days_ahead=7,
)

# Two customers on purpose: it makes the double-booking race reproducible by hand.
CUSTOMERS = {"5491122334455": "Ana", "5491199887766": "Bruno"}

BUTTON_PREFIXES = ("menu:", "confirm:", "cancelconfirm:")

# The simulator is a single tenant; its id must match what meta_payload() stamps.
DEMO_PHONE_NUMBER_ID = "demo-number"

# Set it to a calendar id and the simulator rehearses against Google itself.
# Unset, it keeps booking into memory, which is what most runs want.
CALENDAR_ID_ENV = "DEMO_CALENDAR_ID"

INDEX_HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


class SimMessage(BaseModel):
    phone: str
    text: str | None = None
    reply_id: str | None = None
    label: str | None = None


def meta_payload(phone: str, name: str, text: str | None = None, reply_id: str | None = None, label: str = "") -> dict:
    """Build the inbound envelope exactly as Meta sends it."""
    message: dict = {
        "from": phone,
        "id": f"wamid.{uuid.uuid4().hex}",
        "timestamp": str(int(datetime.now().timestamp())),
    }
    if reply_id:
        reply = {"id": reply_id, "title": label[:24] or reply_id[:24]}
        kind = "button_reply" if reply_id.startswith(BUTTON_PREFIXES) else "list_reply"
        message |= {"type": "interactive", "interactive": {"type": kind, kind: reply}}
    else:
        message |= {"type": "text", "text": {"body": text or ""}}

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "0", "phone_number_id": DEMO_PHONE_NUMBER_ID},
                            "contacts": [{"wa_id": phone, "profile": {"name": name}}],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def build_app():
    # Imported here, not at module scope: bot.main reaches back into this module
    # for the demo business, and a top-level import would close the circle.
    from bot.main import build_calendar, google_credentials

    calendar_id = os.getenv(CALENDAR_ID_ENV) or None
    calendar = build_calendar(DEMO_BUSINESS, calendar_id, credentials=google_credentials())
    channel = SimulatorChannel()
    bot = Bot(config=DEMO_BUSINESS, calendar=calendar, sessions=InMemorySessionStore())

    registry = TenantRegistry(
        [Tenant(id=DEMO_PHONE_NUMBER_ID, config=DEMO_BUSINESS, bot=bot, channel=channel)]
    )
    app = create_app(registry=registry, verify_token="simulador")
    processor = app.state.processor

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/sim/customers")
    def customers() -> dict:
        return {"business": DEMO_BUSINESS.name, "customers": CUSTOMERS}

    @app.post("/sim/send")
    def send(message: SimMessage) -> dict:
        name = CUSTOMERS.get(message.phone, "Cliente")
        channel.record_customer(message.phone, message.label or message.text or "")
        payload = meta_payload(
            phone=message.phone,
            name=name,
            text=message.text,
            reply_id=message.reply_id,
            label=message.label or "",
        )
        processor.process(processor.claim(payload))
        return {"ok": True}

    @app.get("/sim/thread")
    def thread(phone: str) -> list[dict]:
        return [entry for entry in channel.thread if entry["to"] == phone]

    @app.post("/sim/reset")
    def reset() -> dict:
        channel.clear()
        return {"ok": True}

    return app


app = build_app()
