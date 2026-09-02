"""Outbound channel that talks to Meta's Cloud API.

Nothing here knows about the conversation. Swapping this in for
SimulatorChannel is the whole migration from local to production.
"""

from __future__ import annotations

import logging

import httpx

from bot.domain.messages import ButtonsMessage, ListMessage, OutgoingMessage, TextMessage

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v21.0"


def to_graph_payload(message: OutgoingMessage) -> dict:
    base = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": message.to}
    match message:
        case TextMessage():
            return {**base, "type": "text", "text": {"preview_url": False, "body": message.body}}
        case ButtonsMessage():
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": message.body},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b.id, "title": b.title}}
                            for b in message.buttons
                        ]
                    },
                },
            }
        case ListMessage():
            section = {
                "title": message.header or "Opciones",
                "rows": [
                    {"id": r.id, "title": r.title, **({"description": r.description} if r.description else {})}
                    for r in message.rows
                ],
            }
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": message.body},
                    "action": {"button": message.button_label, "sections": [section]},
                },
            }
    raise TypeError(f"unknown outgoing message: {message!r}")


class WhatsAppChannel:
    def __init__(self, access_token: str, phone_number_id: str, timeout: float = 10.0) -> None:
        self._url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._timeout = timeout

    def send(self, message: OutgoingMessage) -> None:
        response = httpx.post(
            self._url,
            json=to_graph_payload(message),
            headers=self._headers,
            timeout=self._timeout,
        )
        if response.is_error:
            # Never raise into the webhook loop: one rejected message must not
            # stop the rest of the conversation.
            logger.error("graph api rejected the message: %s %s", response.status_code, response.text)
