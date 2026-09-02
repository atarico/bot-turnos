"""In-memory conversation state.

Fine for the simulator and for a single process. The day this runs on more than
one worker, swap it for Redis behind the same port — nothing else changes.
"""

from __future__ import annotations

from bot.domain.session import Session


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, phone: str) -> Session:
        return self._sessions.setdefault(phone, Session(phone=phone))

    def save(self, session: Session) -> None:
        self._sessions[session.phone] = session
