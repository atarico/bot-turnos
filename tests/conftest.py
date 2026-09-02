from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.adapters.calendar_fake import FakeCalendar
from bot.adapters.session_store import InMemorySessionStore
from bot.domain.bot import Bot
from bot.domain.config import BusinessConfig, Service
from bot.domain.messages import IncomingMessage

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
NOW = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)  # Tuesday
CUSTOMER = "5491122334455"
OTHER = "5491199887766"


def build_bot(open_hour: int = 9, close_hour: int = 13) -> tuple[Bot, FakeCalendar]:
    config = BusinessConfig(
        name="Peluqueria Rivadavia",
        timezone="America/Argentina/Buenos_Aires",
        services=(
            Service(id="corte", name="Corte", duration_minutes=30),
            Service(id="color", name="Color y peinado", duration_minutes=60),
        ),
        open_hour=open_hour,
        close_hour=close_hour,
        slot_step_minutes=30,
        days_ahead=3,
    )
    calendar = FakeCalendar(config, clock=lambda: NOW)
    bot = Bot(
        config=config,
        calendar=calendar,
        sessions=InMemorySessionStore(),
        clock=lambda: NOW,
    )
    return bot, calendar


@pytest.fixture
def setup():
    return build_bot()


def txt(body: str, phone: str = CUSTOMER, mid: str = "wamid.1") -> IncomingMessage:
    return IncomingMessage(message_id=mid, phone=phone, name="Ata", text=body, reply_id=None)


def tap(reply_id: str, phone: str = CUSTOMER, mid: str = "wamid.1") -> IncomingMessage:
    return IncomingMessage(message_id=mid, phone=phone, name="Ata", text=None, reply_id=reply_id)


def walk_to_confirmation(bot: Bot, phone: str = CUSTOMER, slot: str = "time:2026-09-01T10:30:00-03:00") -> None:
    bot.handle(txt("hola", phone=phone))
    bot.handle(tap("menu:book", phone=phone))
    bot.handle(tap("svc:corte", phone=phone))
    bot.handle(tap("day:2026-09-01", phone=phone))
    bot.handle(tap(slot, phone=phone))


def book(bot: Bot, phone: str = CUSTOMER, slot: str = "time:2026-09-01T10:30:00-03:00") -> None:
    walk_to_confirmation(bot, phone=phone, slot=slot)
    bot.handle(tap("confirm:yes", phone=phone))
