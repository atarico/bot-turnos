"""The conversation engine.

Deliberately deterministic: a tap on a button or a list row is the ONLY thing
that advances the flow. Free text never does. Interpreting "el jueves a las 3"
is exactly how a booking bot invents an appointment that does not exist, so
when the customer types instead of tapping we simply ask again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Sequence, TypeVar

from . import copy
from .config import BusinessConfig
from .messages import (
    MAX_ROW_TITLE,
    MAX_ROWS,
    Button,
    ButtonsMessage,
    IncomingMessage,
    ListMessage,
    OutgoingMessage,
    Row,
    TextMessage,
)
from .models import Appointment, Slot, SlotTaken
from .ports import CalendarPort, SessionStorePort
from .session import Session, State

T = TypeVar("T")

ROWS_PER_PAGE = MAX_ROWS - 1  # the last row is reserved for "see more"


class Bot:
    def __init__(
        self,
        *,
        config: BusinessConfig,
        calendar: CalendarPort,
        sessions: SessionStorePort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.calendar = calendar
        self.sessions = sessions
        self._clock = clock or (lambda: datetime.now(config.tz))

    def handle(self, incoming: IncomingMessage) -> list[OutgoingMessage]:
        session = self.sessions.get(incoming.phone)
        try:
            return self._route(session, incoming)
        finally:
            self.sessions.save(session)

    # -- routing -----------------------------------------------------------

    def _route(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        reply = incoming.reply_id
        if reply:
            if reply.startswith("menu:"):
                return self._menu_choice(session, incoming, reply.removeprefix("menu:"))
            if reply.startswith("more:"):
                session.page += 1
                return self._render(session, incoming)
            if session.state is State.CHOOSING_SERVICE and reply.startswith("svc:"):
                return self._pick_service(session, incoming, reply.removeprefix("svc:"))
            if session.state is State.CHOOSING_DAY and reply.startswith("day:"):
                return self._pick_day(session, incoming, reply.removeprefix("day:"))
            if session.state is State.CHOOSING_TIME and reply.startswith("time:"):
                return self._pick_time(session, incoming, reply.removeprefix("time:"))
            if session.state is State.CONFIRMING and reply.startswith("confirm:"):
                return self._finish_booking(session, incoming, reply == "confirm:yes")
            if session.state is State.CHOOSING_CANCEL and reply.startswith("cancel:"):
                return self._pick_cancellation(session, incoming, reply.removeprefix("cancel:"))
            if session.state is State.CONFIRMING_CANCEL and reply.startswith("cancelconfirm:"):
                return self._finish_cancellation(session, incoming, reply == "cancelconfirm:yes")

        # Unknown tap, free text, a voice note: repeat where we are.
        return self._render(session, incoming)

    def _render(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        match session.state:
            case State.CHOOSING_SERVICE:
                return self._ask_service(session, incoming)
            case State.CHOOSING_DAY:
                return self._ask_day(session, incoming)
            case State.CHOOSING_TIME:
                return self._ask_time(session, incoming)
            case State.CONFIRMING:
                return self._ask_confirmation(session, incoming)
            case State.CHOOSING_CANCEL:
                return self._ask_which_to_cancel(session, incoming)
            case State.CONFIRMING_CANCEL:
                return self._ask_cancel_confirmation(session, incoming)
            case _:
                return self._main_menu(session, incoming)

    # -- menu --------------------------------------------------------------

    def _main_menu(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        session.reset()
        return [
            ButtonsMessage(
                to=incoming.phone,
                body=copy.GREETING.format(business=self.config.name),
                buttons=[
                    Button("menu:book", copy.BTN_BOOK),
                    Button("menu:mine", copy.BTN_MINE),
                    Button("menu:cancel", copy.BTN_CANCEL),
                ],
            )
        ]

    def _menu_choice(self, session: Session, incoming: IncomingMessage, choice: str) -> list[OutgoingMessage]:
        match choice:
            case "book":
                session.go(State.CHOOSING_SERVICE)
                return self._ask_service(session, incoming)
            case "mine":
                return self._list_mine(session, incoming)
            case "cancel":
                return self._start_cancellation(session, incoming)
            case _:
                return self._main_menu(session, incoming)

    # -- booking -----------------------------------------------------------

    def _ask_service(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        rows = self._paginate(
            session,
            list(self.config.services),
            "more:services",
            lambda s: Row(
                id=f"svc:{s.id}",
                title=s.name[:MAX_ROW_TITLE],
                description=f"{s.duration_minutes} min",
            ),
        )
        return [
            ListMessage(
                to=incoming.phone,
                body=copy.ASK_SERVICE,
                button_label=copy.ASK_SERVICE_ACTION,
                rows=rows,
            )
        ]

    def _pick_service(self, session: Session, incoming: IncomingMessage, service_id: str) -> list[OutgoingMessage]:
        service = self.config.service(service_id)
        if service is None:
            return self._ask_service(session, incoming)
        session.service_id = service.id
        session.go(State.CHOOSING_DAY)
        return self._ask_day(session, incoming)

    def _ask_day(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        rows = self._paginate(
            session,
            self._offered_days(),
            "more:days",
            lambda d: Row(id=f"day:{d.isoformat()}", title=self._day_label(d), description=self._day_hint(d)),
        )
        return [
            ListMessage(
                to=incoming.phone,
                body=copy.ASK_DAY,
                button_label=copy.ASK_DAY_ACTION,
                rows=rows,
            )
        ]

    def _pick_day(self, session: Session, incoming: IncomingMessage, raw: str) -> list[OutgoingMessage]:
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            return self._ask_day(session, incoming)
        session.day = day
        session.go(State.CHOOSING_TIME)
        return self._ask_time(session, incoming)

    def _ask_time(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        service = self.config.service(session.service_id or "")
        if service is None or session.day is None:
            return self._main_menu(session, incoming)

        slots = self.calendar.available_slots(service, session.day)
        if not slots:
            session.go(State.CHOOSING_DAY)
            return [
                TextMessage(to=incoming.phone, body=copy.NO_SLOTS),
                *self._ask_day(session, incoming),
            ]

        rows = self._paginate(
            session,
            slots,
            "more:times",
            lambda s: Row(
                id=f"time:{s.start.isoformat()}",
                title=s.start.strftime("%H:%M"),
                description=f"{service.name} · {service.duration_minutes} min",
            ),
        )
        return [
            ListMessage(
                to=incoming.phone,
                body=copy.ASK_TIME.format(day=self._day_label(session.day)),
                button_label=copy.ASK_TIME_ACTION,
                rows=rows,
            )
        ]

    def _pick_time(self, session: Session, incoming: IncomingMessage, raw: str) -> list[OutgoingMessage]:
        try:
            start = datetime.fromisoformat(raw)
        except ValueError:
            return self._ask_time(session, incoming)
        session.slot_start = start.astimezone(self.config.tz)
        session.go(State.CONFIRMING)
        return self._ask_confirmation(session, incoming)

    def _ask_confirmation(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        service = self.config.service(session.service_id or "")
        if service is None or session.slot_start is None:
            return self._main_menu(session, incoming)
        return [
            ButtonsMessage(
                to=incoming.phone,
                body=copy.CONFIRM.format(
                    service=service.name,
                    day=self._day_label(session.slot_start.date()),
                    time=session.slot_start.strftime("%H:%M"),
                ),
                buttons=[
                    Button("confirm:yes", copy.BTN_CONFIRM_YES),
                    Button("confirm:no", copy.BTN_CONFIRM_NO),
                ],
            )
        ]

    def _finish_booking(self, session: Session, incoming: IncomingMessage, confirmed: bool) -> list[OutgoingMessage]:
        service = self.config.service(session.service_id or "")
        if not confirmed or service is None or session.slot_start is None:
            return self._main_menu(session, incoming)

        slot = Slot(start=session.slot_start, service=service)
        try:
            self.calendar.book(slot, incoming.phone, incoming.name or "")
        except SlotTaken:
            # Two customers were shown the same slot and both tapped it. The
            # calendar is the only authority, so the loser is sent back to pick again.
            session.go(State.CHOOSING_TIME)
            return [
                TextMessage(to=incoming.phone, body=copy.SLOT_TAKEN),
                *self._ask_time(session, incoming),
            ]

        body = copy.BOOKED.format(
            service=service.name,
            day=self._day_label(slot.start.date()),
            time=slot.start.strftime("%H:%M"),
            business=self.config.name,
        )
        session.reset()
        return [TextMessage(to=incoming.phone, body=body)]

    # -- consulting and cancelling ----------------------------------------

    def _list_mine(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        appointments = self.calendar.appointments_for(incoming.phone)
        session.reset()
        if not appointments:
            return [TextMessage(to=incoming.phone, body=copy.MINE_EMPTY)]
        lines = "\n".join(
            copy.MINE_LINE.format(
                service=a.slot.service.name,
                day=self._day_label(a.slot.start.date()),
                time=a.slot.start.strftime("%H:%M"),
            )
            for a in appointments
        )
        return [TextMessage(to=incoming.phone, body=copy.MINE_LIST.format(lines=lines))]

    def _start_cancellation(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        if not self.calendar.appointments_for(incoming.phone):
            session.reset()
            return [TextMessage(to=incoming.phone, body=copy.CANCEL_EMPTY)]
        session.go(State.CHOOSING_CANCEL)
        return self._ask_which_to_cancel(session, incoming)

    def _ask_which_to_cancel(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        appointments = self.calendar.appointments_for(incoming.phone)
        if not appointments:
            return self._main_menu(session, incoming)
        rows = self._paginate(
            session,
            appointments,
            "more:cancel",
            lambda a: Row(
                id=f"cancel:{a.id}",
                title=f"{self._day_label(a.slot.start.date())} {a.slot.start.strftime('%H:%M')}"[:MAX_ROW_TITLE],
                description=a.slot.service.name,
            ),
        )
        return [
            ListMessage(
                to=incoming.phone,
                body=copy.CANCEL_ASK,
                button_label=copy.CANCEL_ACTION,
                rows=rows,
            )
        ]

    def _pick_cancellation(self, session: Session, incoming: IncomingMessage, appointment_id: str) -> list[OutgoingMessage]:
        session.go(State.CONFIRMING_CANCEL)
        session.appointment_id = appointment_id
        return self._ask_cancel_confirmation(session, incoming)

    def _ask_cancel_confirmation(self, session: Session, incoming: IncomingMessage) -> list[OutgoingMessage]:
        appointment = self._find(incoming.phone, session.appointment_id)
        if appointment is None:
            return self._main_menu(session, incoming)
        return [
            ButtonsMessage(
                to=incoming.phone,
                body=copy.CANCEL_CONFIRM.format(
                    service=appointment.slot.service.name,
                    day=self._day_label(appointment.slot.start.date()),
                    time=appointment.slot.start.strftime("%H:%M"),
                ),
                buttons=[
                    Button("cancelconfirm:yes", copy.BTN_CANCEL_YES),
                    Button("cancelconfirm:no", copy.BTN_CANCEL_NO),
                ],
            )
        ]

    def _finish_cancellation(self, session: Session, incoming: IncomingMessage, confirmed: bool) -> list[OutgoingMessage]:
        if not confirmed or session.appointment_id is None:
            return self._main_menu(session, incoming)
        self.calendar.cancel(session.appointment_id)
        session.reset()
        return [TextMessage(to=incoming.phone, body=copy.CANCELLED)]

    def _find(self, phone: str, appointment_id: str | None) -> Appointment | None:
        if appointment_id is None:
            return None
        return next((a for a in self.calendar.appointments_for(phone) if a.id == appointment_id), None)

    # -- helpers -----------------------------------------------------------

    def _offered_days(self) -> list[date]:
        today = self._clock().date()
        days: list[date] = []
        offset = 0
        limit = self.config.days_ahead * 3  # guard against a business closed most of the week
        while len(days) < self.config.days_ahead and offset < limit:
            candidate = today + timedelta(days=offset)
            if candidate.weekday() not in self.config.closed_weekdays:
                days.append(candidate)
            offset += 1
        return days

    def _day_label(self, day: date) -> str:
        return f"{copy.WEEKDAYS[day.weekday()]} {day.day:02d}/{day.month:02d}"

    def _day_hint(self, day: date) -> str:
        today = self._clock().date()
        if day == today:
            return "Hoy"
        if day == today + timedelta(days=1):
            return "Mañana"
        return ""

    def _paginate(
        self,
        session: Session,
        items: Sequence[T],
        more_id: str,
        to_row: Callable[[T], Row],
    ) -> list[Row]:
        rows = self._slice(items, session.page, more_id, to_row)
        if not rows and items:
            session.page = 0
            rows = self._slice(items, 0, more_id, to_row)
        return rows

    @staticmethod
    def _slice(
        items: Sequence[T],
        page: int,
        more_id: str,
        to_row: Callable[[T], Row],
    ) -> list[Row]:
        offset = page * ROWS_PER_PAGE
        window = items[offset : offset + MAX_ROWS]
        if len(window) > ROWS_PER_PAGE:
            return [to_row(item) for item in window[:ROWS_PER_PAGE]] + [Row(id=more_id, title=copy.MORE_ROW)]
        return [to_row(item) for item in window]
