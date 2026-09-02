"""Parsing of Meta's inbound webhook payload.

This is the reason the project is in Python. Meta sends deeply nested JSON from
the network, with a shape that varies by message type and that also carries
delivery-status events we must ignore. Pydantic validates it at runtime, which
is precisely what a static type annotation cannot do.

Every model is lenient on purpose: an unknown field or a new message type must
never take the webhook down.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bot.domain.messages import IncomingMessage

_LENIENT = ConfigDict(extra="ignore", populate_by_name=True)


class _Text(BaseModel):
    model_config = _LENIENT
    body: str = ""


class _Reply(BaseModel):
    model_config = _LENIENT
    id: str = ""
    title: str = ""


class _Interactive(BaseModel):
    model_config = _LENIENT
    type: str = ""
    button_reply: _Reply | None = None
    list_reply: _Reply | None = None


class _Message(BaseModel):
    model_config = _LENIENT
    id: str = ""
    sender: str = Field(default="", alias="from")
    type: str = ""
    text: _Text | None = None
    interactive: _Interactive | None = None


class _Profile(BaseModel):
    model_config = _LENIENT
    name: str = ""


class _Contact(BaseModel):
    model_config = _LENIENT
    wa_id: str = ""
    profile: _Profile = Field(default_factory=_Profile)


class _Metadata(BaseModel):
    model_config = _LENIENT
    phone_number_id: str = ""


class _Value(BaseModel):
    model_config = _LENIENT
    metadata: _Metadata = Field(default_factory=_Metadata)
    messages: list[_Message] = Field(default_factory=list)
    contacts: list[_Contact] = Field(default_factory=list)


class _Change(BaseModel):
    model_config = _LENIENT
    value: _Value = Field(default_factory=_Value)


class _Entry(BaseModel):
    model_config = _LENIENT
    changes: list[_Change] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    model_config = _LENIENT
    entry: list[_Entry] = Field(default_factory=list)


def parse_incoming(payload: dict) -> list[IncomingMessage]:
    """Extract the customer messages from a webhook payload. Never raises."""
    try:
        parsed = WebhookPayload.model_validate(payload)
    except ValidationError:
        return []

    messages: list[IncomingMessage] = []
    for entry in parsed.entry:
        for change in entry.changes:
            names = {c.wa_id: c.profile.name for c in change.value.contacts}
            for message in change.value.messages:
                messages.append(
                    IncomingMessage(
                        message_id=message.id,
                        phone=message.sender,
                        name=names.get(message.sender) or None,
                        text=message.text.body if message.type == "text" and message.text else None,
                        reply_id=_reply_id(message),
                        phone_number_id=change.value.metadata.phone_number_id,
                    )
                )
    return messages


def _reply_id(message: _Message) -> str | None:
    if message.type != "interactive" or message.interactive is None:
        return None
    interactive = message.interactive
    reply = interactive.button_reply or interactive.list_reply
    return reply.id if reply and reply.id else None
