"""One deploy, many businesses.

Meta puts `metadata.phone_number_id` in every inbound payload: that is which of
our numbers received the message, and therefore which business it belongs to.
It is the tenant key, and it arrives for free -- we were simply ignoring it.

Each tenant owns its own Bot, which owns its own calendar, its own session
store and its own booking lock. Nothing is shared between businesses except the
process itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.domain.bot import Bot
from bot.domain.config import BusinessConfig
from bot.domain.ports import ChannelPort


@dataclass(frozen=True)
class Tenant:
    id: str
    """The WhatsApp phone_number_id that identifies this business."""
    config: BusinessConfig
    bot: Bot
    channel: ChannelPort


class TenantRegistry:
    def __init__(self, tenants: list[Tenant] | None = None) -> None:
        self._tenants: dict[str, Tenant] = {t.id: t for t in (tenants or [])}

    def add(self, tenant: Tenant) -> None:
        self._tenants[tenant.id] = tenant

    def get(self, phone_number_id: str) -> Tenant | None:
        return self._tenants.get(phone_number_id)

    def __len__(self) -> int:
        return len(self._tenants)

    def __iter__(self):
        return iter(self._tenants.values())
