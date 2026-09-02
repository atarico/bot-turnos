from fastapi.testclient import TestClient

from bot.adapters.channel_simulator import SimulatorChannel
from bot.tenants import Tenant, TenantRegistry
from bot.webhook import create_app

from .conftest import build_bot
from .test_meta_payload import DEFAULT_PHONE_NUMBER_ID, envelope, value_with

VERIFY_TOKEN = "un-token-secreto"


def client_and_channel():
    bot, _ = build_bot()
    channel = SimulatorChannel()
    registry = TenantRegistry(
        [Tenant(id=DEFAULT_PHONE_NUMBER_ID, config=bot.config, bot=bot, channel=channel)]
    )
    app = create_app(registry=registry, verify_token=VERIFY_TOKEN)
    return TestClient(app), channel


def text_payload(body: str, message_id: str = "wamid.1", phone_number_id: str = DEFAULT_PHONE_NUMBER_ID) -> dict:
    return envelope(
        value_with(
            {
                "from": "5491122334455",
                "id": message_id,
                "timestamp": "1772000000",
                "type": "text",
                "text": {"body": body},
            },
            phone_number_id=phone_number_id,
        )
    )


def test_verification_handshake_echoes_the_challenge():
    client, _ = client_and_channel()

    response = client.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"},
    )

    assert response.status_code == 200
    assert response.text == "12345"


def test_verification_with_a_wrong_token_is_forbidden():
    client, _ = client_and_channel()

    response = client.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "12345"},
    )

    assert response.status_code == 403


def test_an_incoming_message_produces_an_outgoing_one():
    client, channel = client_and_channel()

    response = client.post("/webhook", json=text_payload("hola"))

    assert response.status_code == 200
    assert len(channel.sent) == 1


def test_a_retried_delivery_is_processed_only_once():
    client, channel = client_and_channel()

    client.post("/webhook", json=text_payload("hola", message_id="wamid.same"))
    client.post("/webhook", json=text_payload("hola", message_id="wamid.same"))

    assert len(channel.sent) == 1


def test_an_unparseable_payload_still_answers_200():
    client, channel = client_and_channel()

    response = client.post("/webhook", json={"object": "whatsapp_business_account"})

    assert response.status_code == 200
    assert channel.sent == []


def test_a_message_for_a_number_we_do_not_serve_is_dropped():
    client, channel = client_and_channel()

    response = client.post("/webhook", json=text_payload("hola", phone_number_id="999-desconocido"))

    assert response.status_code == 200
    assert channel.sent == []
