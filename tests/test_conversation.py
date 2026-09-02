from datetime import datetime

import pytest

from bot.domain.messages import ButtonsMessage, ListMessage, TextMessage

from .conftest import CUSTOMER, OTHER, TZ, book, build_bot, tap, txt, walk_to_confirmation


def test_any_greeting_opens_the_main_menu(setup):
    bot, _ = setup

    out = bot.handle(txt("hola"))

    assert len(out) == 1
    assert isinstance(out[0], ButtonsMessage)
    assert [b.id for b in out[0].buttons] == ["menu:book", "menu:mine", "menu:cancel"]


def test_booking_happy_path_creates_the_appointment(setup):
    bot, calendar = setup

    out = bot.handle(txt("hola"))
    out = bot.handle(tap("menu:book"))
    assert isinstance(out[0], ListMessage)
    assert [r.id for r in out[0].rows] == ["svc:corte", "svc:color"]

    out = bot.handle(tap("svc:corte"))
    assert [r.id for r in out[0].rows] == [
        "day:2026-09-01",
        "day:2026-09-02",
        "day:2026-09-03",
    ]

    out = bot.handle(tap("day:2026-09-01"))
    # Open 09-13, now is 10:00, so only future slots that still fit a 30' service.
    assert [r.id for r in out[0].rows] == [
        "time:2026-09-01T10:30:00-03:00",
        "time:2026-09-01T11:00:00-03:00",
        "time:2026-09-01T11:30:00-03:00",
        "time:2026-09-01T12:00:00-03:00",
        "time:2026-09-01T12:30:00-03:00",
    ]

    out = bot.handle(tap("time:2026-09-01T10:30:00-03:00"))
    assert isinstance(out[0], ButtonsMessage)
    assert [b.id for b in out[0].buttons] == ["confirm:yes", "confirm:no"]

    out = bot.handle(tap("confirm:yes"))
    assert isinstance(out[0], TextMessage)

    appointments = calendar.appointments_for(CUSTOMER)
    assert len(appointments) == 1
    assert appointments[0].slot.start == datetime(2026, 9, 1, 10, 30, tzinfo=TZ)
    assert appointments[0].slot.service.id == "corte"


def test_free_text_mid_flow_repeats_the_prompt_instead_of_guessing(setup):
    bot, calendar = setup
    bot.handle(txt("hola"))
    bot.handle(tap("menu:book"))

    out = bot.handle(txt("dale el jueves a las 3 mas o menos"))

    assert isinstance(out[0], ListMessage)
    assert [r.id for r in out[0].rows] == ["svc:corte", "svc:color"]
    assert calendar.appointments_for(CUSTOMER) == []


def test_slot_taken_between_offer_and_confirm_is_rejected(setup):
    bot, calendar = setup
    walk_to_confirmation(bot, phone=CUSTOMER)

    book(bot, phone=OTHER)

    out = bot.handle(tap("confirm:yes", phone=CUSTOMER))

    assert isinstance(out[0], TextMessage)
    assert "ya no esta disponible" in out[0].body.lower().replace("á", "a")
    assert calendar.appointments_for(CUSTOMER) == []
    assert len(calendar.appointments_for(OTHER)) == 1


def test_a_booked_slot_is_no_longer_offered(setup):
    bot, _ = setup
    book(bot, phone=OTHER)

    bot.handle(txt("hola"))
    bot.handle(tap("menu:book"))
    bot.handle(tap("svc:corte"))
    out = bot.handle(tap("day:2026-09-01"))

    assert "time:2026-09-01T10:30:00-03:00" not in [r.id for r in out[0].rows]


def test_a_longer_service_needs_room_for_its_whole_duration(setup):
    bot, _ = setup
    bot.handle(txt("hola"))
    bot.handle(tap("menu:book"))
    bot.handle(tap("svc:color"))  # 60 minutes
    out = bot.handle(tap("day:2026-09-01"))

    # Closing at 13:00 means the last 60' slot can only start at 12:00.
    assert [r.id for r in out[0].rows][-1] == "time:2026-09-01T12:00:00-03:00"


def test_my_appointments_when_there_are_none(setup):
    bot, _ = setup
    bot.handle(txt("hola"))

    out = bot.handle(tap("menu:mine"))

    assert isinstance(out[0], TextMessage)
    assert "no ten" in out[0].body.lower()


def test_my_appointments_lists_what_was_booked(setup):
    bot, _ = setup
    book(bot)

    out = bot.handle(tap("menu:mine"))

    assert isinstance(out[0], TextMessage)
    assert "Corte" in out[0].body
    assert "10:30" in out[0].body


def test_cancel_flow_removes_the_appointment(setup):
    bot, calendar = setup
    book(bot)

    out = bot.handle(tap("menu:cancel"))
    assert isinstance(out[0], ListMessage)
    row_id = out[0].rows[0].id
    assert row_id.startswith("cancel:")

    out = bot.handle(tap(row_id))
    assert [b.id for b in out[0].buttons] == ["cancelconfirm:yes", "cancelconfirm:no"]

    out = bot.handle(tap("cancelconfirm:yes"))
    assert isinstance(out[0], TextMessage)
    assert calendar.appointments_for(CUSTOMER) == []


def test_cancel_with_nothing_booked_says_so(setup):
    bot, _ = setup
    bot.handle(txt("hola"))

    out = bot.handle(tap("menu:cancel"))

    assert isinstance(out[0], TextMessage)


def test_declining_the_confirmation_books_nothing(setup):
    bot, calendar = setup
    walk_to_confirmation(bot)

    out = bot.handle(tap("confirm:no"))

    assert calendar.appointments_for(CUSTOMER) == []
    assert isinstance(out[0], ButtonsMessage)  # back to the menu


def test_time_list_paginates_because_whatsapp_caps_rows_at_ten():
    bot, _ = build_bot(open_hour=9, close_hour=18)
    bot.handle(txt("hola"))
    bot.handle(tap("menu:book"))
    bot.handle(tap("svc:corte"))

    out = bot.handle(tap("day:2026-09-01"))
    assert len(out[0].rows) == 10
    assert out[0].rows[-1].id == "more:times"
    assert out[0].rows[0].id == "time:2026-09-01T10:30:00-03:00"

    out = bot.handle(tap("more:times"))
    assert out[0].rows[0].id == "time:2026-09-01T15:00:00-03:00"
    assert "more:times" not in [r.id for r in out[0].rows]


def test_two_customers_keep_separate_conversations(setup):
    bot, _ = setup
    bot.handle(txt("hola", phone=CUSTOMER))
    bot.handle(tap("menu:book", phone=CUSTOMER))

    out = bot.handle(txt("buenas", phone=OTHER))

    assert isinstance(out[0], ButtonsMessage)  # OTHER starts at the menu
