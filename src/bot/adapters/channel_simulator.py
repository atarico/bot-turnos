"""Outbound channel that keeps messages in memory instead of calling Meta."""

from __future__ import annotations

from bot.domain.messages import ButtonsMessage, ListMessage, OutgoingMessage, TextMessage


def serialize(message: OutgoingMessage) -> dict:
    match message:
        case TextMessage():
            return {"kind": "text", "body": message.body, "action": "", "options": []}
        case ButtonsMessage():
            return {
                "kind": "buttons",
                "body": message.body,
                "action": "",
                "options": [{"id": b.id, "title": b.title, "description": ""} for b in message.buttons],
            }
        case ListMessage():
            return {
                "kind": "list",
                "body": message.body,
                "action": message.button_label,
                "options": [
                    {"id": r.id, "title": r.title, "description": r.description} for r in message.rows
                ],
            }
    raise TypeError(f"unknown outgoing message: {message!r}")


class SimulatorChannel:
    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        self.thread: list[dict] = []

    def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)
        self.thread.append({"role": "bot", "to": message.to, **serialize(message)})

    def record_customer(self, phone: str, body: str) -> None:
        self.thread.append(
            {"role": "customer", "to": phone, "kind": "text", "body": body, "action": "", "options": []}
        )

    def clear(self) -> None:
        self.sent.clear()
        self.thread.clear()
