"""Channel-agnostic messages.

The size limits below are WhatsApp's, enforced here on purpose: a list with
eleven rows is rejected by the Graph API at send time, which is the worst place
to find out. Failing in the domain keeps that bug out of production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

MAX_BUTTONS = 3
MAX_ROWS = 10
MAX_BUTTON_TITLE = 20
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    phone: str
    name: str | None = None
    text: str | None = None
    reply_id: str | None = None
    phone_number_id: str = ""
    """Which of our numbers received this. This is the tenant key."""


@dataclass(frozen=True)
class Button:
    id: str
    title: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.title) <= MAX_BUTTON_TITLE:
            raise ValueError(f"button title must be 1..{MAX_BUTTON_TITLE} chars: {self.title!r}")


@dataclass(frozen=True)
class Row:
    id: str
    title: str
    description: str = ""

    def __post_init__(self) -> None:
        if not 1 <= len(self.title) <= MAX_ROW_TITLE:
            raise ValueError(f"row title must be 1..{MAX_ROW_TITLE} chars: {self.title!r}")
        if len(self.description) > MAX_ROW_DESCRIPTION:
            raise ValueError(f"row description must be <= {MAX_ROW_DESCRIPTION} chars")


@dataclass(frozen=True)
class TextMessage:
    to: str
    body: str


@dataclass(frozen=True)
class ButtonsMessage:
    to: str
    body: str
    buttons: Sequence[Button] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 1 <= len(self.buttons) <= MAX_BUTTONS:
            raise ValueError(f"WhatsApp allows 1..{MAX_BUTTONS} buttons, got {len(self.buttons)}")


@dataclass(frozen=True)
class ListMessage:
    to: str
    body: str
    button_label: str
    rows: Sequence[Row] = field(default_factory=tuple)
    header: str = ""

    def __post_init__(self) -> None:
        if not 1 <= len(self.rows) <= MAX_ROWS:
            raise ValueError(f"WhatsApp allows 1..{MAX_ROWS} rows, got {len(self.rows)}")


OutgoingMessage = TextMessage | ButtonsMessage | ListMessage
