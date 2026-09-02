"""One deploy serving two businesses.

The same customer, on the same phone, holds two independent conversations --
one per business -- because the tenant key comes from which of our numbers
received the message.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bot.adapters.channel_simulator import SimulatorChannel
from bot.domain.messages import ButtonsMessage, ListMessage
from bot.tenants import Tenant, TenantRegistry
from bot.webhook import create_app

from .conftest import CUSTOMER, build_bot
from .test_meta_payload import envelope, value_with

PELUQUERIA = "111"
KINESIO = "222"


def two_tenants():
    peluqueria_bot, peluqueria_cal = build_bot()
    kinesio_bot, kinesio_cal = build_bot()
    peluqueria_channel, kinesio_channel = SimulatorChannel(), SimulatorChannel()

    registry = TenantRegistry(
        [
            Tenant(id=PELUQUERIA, config=peluqueria_bot.config, bot=peluqueria_bot, channel=peluqueria_channel),
            Tenant(id=KINESIO, config=kinesio_bot.config, bot=kinesio_bot, channel=kinesio_channel),
        ]
    )
    app = create_app(registry=registry, verify_token="t")
    return TestClient(app), {
        PELUQUERIA: (peluqueria_channel, peluqueria_cal),
        KINESIO: (kinesio_channel, kinesio_cal),
    }


def send(client: TestClient, phone_number_id: str, *, text=None, reply_id=None, message_id="wamid.x") -> None:
    message = {"from": CUSTOMER, "id": message_id, "timestamp": "1772000000"}
    if reply_id:
        message |= {
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": reply_id, "title": "x"}},
        }
    else:
        message |= {"type": "text", "text": {"body": text or ""}}
    client.post("/webhook", json=envelope(value_with(message, phone_number_id=phone_number_id)))


def test_each_business_answers_on_its_own_channel():
    client, tenants = two_tenants()

    send(client, PELUQUERIA, text="hola", message_id="wamid.1")

    assert len(tenants[PELUQUERIA][0].sent) == 1
    assert tenants[KINESIO][0].sent == []


def test_the_same_customer_holds_two_independent_conversations():
    client, tenants = two_tenants()

    # Deep into the flow with the first business...
    send(client, PELUQUERIA, text="hola", message_id="wamid.1")
    send(client, PELUQUERIA, reply_id="menu:book", message_id="wamid.2")

    # ...while the second one is still a fresh conversation.
    send(client, KINESIO, text="hola", message_id="wamid.3")

    assert isinstance(tenants[PELUQUERIA][0].sent[-1], ListMessage)  # choosing a service
    assert isinstance(tenants[KINESIO][0].sent[-1], ButtonsMessage)  # main menu


def test_booking_with_one_business_never_touches_the_other_calendar():
    client, tenants = two_tenants()

    for message_id, step in enumerate(
        [
            {"text": "hola"},
            {"reply_id": "menu:book"},
            {"reply_id": "svc:corte"},
            {"reply_id": "day:2026-09-01"},
            {"reply_id": "time:2026-09-01T10:30:00-03:00"},
            {"reply_id": "confirm:yes"},
        ]
    ):
        send(client, PELUQUERIA, message_id=f"wamid.{message_id}", **step)

    assert len(tenants[PELUQUERIA][1].appointments_for(CUSTOMER)) == 1
    assert tenants[KINESIO][1].appointments_for(CUSTOMER) == []
