from bot.adapters.meta_payload import parse_incoming


def envelope(value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "102290129340398", "changes": [{"value": value, "field": "messages"}]}],
    }


DEFAULT_PHONE_NUMBER_ID = "106540352242922"


def value_with(message: dict, phone_number_id: str = DEFAULT_PHONE_NUMBER_ID) -> dict:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550783881", "phone_number_id": phone_number_id},
        "contacts": [{"profile": {"name": "Ata"}, "wa_id": "5491122334455"}],
        "messages": [message],
    }


def test_parses_a_plain_text_message():
    payload = envelope(
        value_with(
            {
                "from": "5491122334455",
                "id": "wamid.HBgLNTQ5MTEyMg",
                "timestamp": "1772000000",
                "type": "text",
                "text": {"body": "hola"},
            }
        )
    )

    [message] = parse_incoming(payload)

    assert message.message_id == "wamid.HBgLNTQ5MTEyMg"
    assert message.phone == "5491122334455"
    assert message.name == "Ata"
    assert message.text == "hola"
    assert message.reply_id is None
    assert message.phone_number_id == DEFAULT_PHONE_NUMBER_ID


def test_parses_a_button_reply():
    payload = envelope(
        value_with(
            {
                "from": "5491122334455",
                "id": "wamid.B",
                "timestamp": "1772000000",
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "menu:book", "title": "Sacar turno"},
                },
            }
        )
    )

    [message] = parse_incoming(payload)

    assert message.reply_id == "menu:book"
    assert message.text is None


def test_parses_a_list_reply():
    payload = envelope(
        value_with(
            {
                "from": "5491122334455",
                "id": "wamid.L",
                "timestamp": "1772000000",
                "type": "interactive",
                "interactive": {
                    "type": "list_reply",
                    "list_reply": {"id": "svc:corte", "title": "Corte", "description": "30 min"},
                },
            }
        )
    )

    [message] = parse_incoming(payload)

    assert message.reply_id == "svc:corte"


def test_delivery_status_events_carry_no_incoming_message():
    payload = envelope(
        {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "1555", "phone_number_id": "106"},
            "statuses": [
                {
                    "id": "wamid.X",
                    "status": "delivered",
                    "timestamp": "1772000000",
                    "recipient_id": "5491122334455",
                }
            ],
        }
    )

    assert parse_incoming(payload) == []


def test_unsupported_media_still_yields_a_message_so_the_bot_can_reprompt():
    payload = envelope(
        value_with(
            {
                "from": "5491122334455",
                "id": "wamid.A",
                "timestamp": "1772000000",
                "type": "audio",
                "audio": {"id": "media-id", "mime_type": "audio/ogg"},
            }
        )
    )

    [message] = parse_incoming(payload)

    assert message.text is None
    assert message.reply_id is None


def test_garbage_payloads_do_not_raise():
    assert parse_incoming({}) == []
    assert parse_incoming({"entry": [{}]}) == []
    assert parse_incoming({"entry": [{"changes": [{"value": {}}]}]}) == []
