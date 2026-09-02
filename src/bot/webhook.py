"""HTTP surface. Meta talks to this, and so does the simulator."""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from bot.adapters.meta_payload import parse_incoming
from bot.domain.messages import IncomingMessage
from bot.tenants import TenantRegistry

logger = logging.getLogger(__name__)

SEEN_LIMIT = 2000


class WebhookProcessor:
    """Claim first, work later.

    Claiming (parse + de-duplicate) is cheap and runs inside the request so the
    200 goes back immediately. Meta retries anything it does not see acknowledged
    within seconds, and a retry processed twice is a duplicate appointment. The
    slow part -- calendar and Graph API calls -- runs after the response.
    """

    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry
        self._seen: dict[str, None] = {}

    def claim(self, payload: dict) -> list[IncomingMessage]:
        fresh: list[IncomingMessage] = []
        for message in parse_incoming(payload):
            if not message.message_id or message.message_id in self._seen:
                continue
            self._seen[message.message_id] = None
            if len(self._seen) > SEEN_LIMIT:
                self._seen.pop(next(iter(self._seen)))
            fresh.append(message)
        return fresh

    def process(self, messages: list[IncomingMessage]) -> None:
        for message in messages:
            tenant = self.registry.get(message.phone_number_id)
            if tenant is None:
                # A number we do not serve, or one removed mid-flight. Dropping
                # it is correct: answering on behalf of an unknown business is worse.
                logger.warning("no tenant for phone_number_id %r", message.phone_number_id)
                continue
            try:
                for outgoing in tenant.bot.handle(message):
                    tenant.channel.send(outgoing)
            except Exception:  # noqa: BLE001 - one bad message must not kill the worker
                logger.exception("failed while handling message %s", message.message_id)


def create_app(
    *,
    registry: TenantRegistry,
    verify_token: str,
    app_secret: str | None = None,
) -> FastAPI:
    app = FastAPI(title="WhatsApp appointment bot")
    processor = WebhookProcessor(registry)
    app.state.processor = processor

    @app.get("/webhook", response_class=PlainTextResponse)
    def verify(
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ) -> str:
        if mode == "subscribe" and hmac.compare_digest(token, verify_token):
            return challenge
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks) -> Response:
        raw = await request.body()
        if app_secret and not _signature_is_valid(raw, request.headers.get("X-Hub-Signature-256"), app_secret):
            raise HTTPException(status_code=403, detail="bad signature")

        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return Response(status_code=200)

        messages = processor.claim(payload if isinstance(payload, dict) else {})
        if messages:
            background.add_task(processor.process, messages)
        return Response(status_code=200)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "tenants": len(registry)}

    return app


def _signature_is_valid(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
