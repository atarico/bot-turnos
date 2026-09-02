# WhatsApp appointment bot

A standalone WhatsApp bot that answers on its own, tells a customer whether they
have an appointment, and walks them through booking one. The business's own
calendar is the single source of truth — there is no dashboard to build and no
habit for the business to change.

Runs today against a **local simulator**. The switch to Meta's Cloud API is an
adapter swap, not a rewrite.

## Run it

```bash
uv sync
uv run uvicorn bot.simulator.app:app --reload --port 8000
# open http://localhost:8000
```

Two customers are wired in (Ana and Bruno) so the double-booking race is
reproducible by hand: walk both to the same slot, let one confirm, then confirm
with the other.

```bash
uv run pytest
```

## Why the simulator is not a toy

`/sim/send` builds the **exact envelope Meta POSTs** and feeds it to the same
`WebhookProcessor` the real webhook uses. Payload parsing, de-duplication, the
state machine and the calendar are all the production ones. A simulator that
invents its own JSON tests a fiction and collapses the day you go live.

## Multi-tenant

One deploy serves many businesses. Meta stamps `metadata.phone_number_id` on
every inbound payload -- which of our numbers received the message, and
therefore which business it belongs to. That is the tenant key, and it arrives
for free.

Each tenant owns its own `Bot`, which owns its own calendar, session store and
booking lock. Nothing is shared between businesses except the process. A message
for a number we do not serve is dropped, never answered.

```bash
TENANTS_FILE=tenants.example.json
GOOGLE_CREDENTIALS_FILE=./service-account.json   # one key serves every tenant
WHATSAPP_TOKEN_PELUQUERIA=...                    # named per tenant in the file
```

Access tokens are read from the environment **by name**, so no secret ever
lands in the tenants file. A tenant with no token talks to the simulator
channel, and a tenant with no calendar id books in memory -- but a tenant that
declares a calendar id with no credentials available **refuses to start**.
Booking into a fake while every screen says the appointment was confirmed is
worse than not booting.

## Design

```
domain/          knows nothing about WhatsApp or Google
  bot.py         the conversation state machine
  messages.py    channel-agnostic messages + WhatsApp's size limits
  copy.py        every string the customer reads
  ports.py       CalendarPort · ChannelPort · SessionStorePort
adapters/
  calendar_fake.py       in-memory  -> swap for Google Calendar
  channel_simulator.py   in-memory  -> swap for channel_whatsapp.py
  meta_payload.py        Pydantic parsing of the inbound webhook
tenants.py       the phone_number_id -> business registry
webhook.py       the HTTP surface Meta talks to
```

Three decisions worth knowing before changing anything:

**The flow is deterministic.** A tap on a button or a list row is the only thing
that advances state. Free text never does. Interpreting "el jueves a las 3" is
how a booking bot invents an appointment that does not exist, so when the
customer types instead of tapping, the bot simply asks again. An LLM belongs at
the edges — never on the booking path.

**The calendar is the only authority.** Two customers can be shown the same slot
and both tap it. The one who confirms second is rejected and sent back to pick
again (`SlotTaken`). A duplicate appointment is worse than no bot at all.

**The webhook claims, then works.** Parsing and de-duplication run inside the
request so the `200` returns immediately; calendar and Graph API calls run after
it. Meta retries anything it does not see acknowledged within seconds, and a
retry processed twice is a duplicate appointment.

WhatsApp's interactive limits (3 buttons, 10 list rows, 20/24-char titles) are
enforced in `messages.py`. The Graph API rejects a violation at send time, which
is the worst possible place to find out.

## Google Calendar

`adapters/google_calendar.py` holds the booking rules and is fully tested with
no network. `adapters/google_api.py` holds nothing but the HTTP client.

**Auth is a service account, not OAuth.** Google's calendar scope is sensitive,
so an OAuth "Connect with Google" button drags the whole app through Google
verification -- a second multi-week review running alongside Meta's. With a
service account the business does one step instead:

1. Create a Google Cloud project, enable the Calendar API, create a service
   account and download its JSON key.
2. In Google Calendar → *Settings for the calendar* → *Share with specific
   people*, add the service account email and grant
   **"Make changes to events"**.
3. Copy the calendar id (usually the business's own email address).

```bash
GOOGLE_CREDENTIALS_FILE=./service-account.json
GOOGLE_CALENDAR_ID=peluqueria@gmail.com
```

Appointments are written as ordinary events carrying
`extendedProperties.private` (`bookedByBot`, `phone`, `service`), which is how
`appointments_for` finds a customer's bookings without a database of our own.
Events the business creates by hand are never mistaken for appointments, and
whatever the owner blocks from their phone stops being offered immediately.

### The limitation you must know about

**Google Calendar has no atomic "insert if free".** Between the availability
check and the write, another caller can take the same slot; both pass the check
and both insert. Booking is therefore defended in three layers: an in-process
lock, a freebusy check inside it, and an optimistic read-back afterwards where
overlapping bot events are ordered by `(created, id)` and the loser deletes its
own event and reports `SlotTaken`.

That last layer leaves a window of a few hundred milliseconds against writers
outside this process. **Do not run more than one worker per calendar.** Closing
the window properly needs a lock shared by the whole fleet (Redis) or an agenda
we own -- which is the honest long-term cost of putting the source of truth in
someone else's product.

## Going live

1. Meta Business account + WhatsApp Business Account, number never used on
   regular WhatsApp (or migrated from the WhatsApp Business app).
2. Point the webhook at a public HTTPS URL; set `WHATSAPP_VERIFY_TOKEN`.
3. Set `WHATSAPP_APP_SECRET` -- `create_app` then enforces the
   `X-Hub-Signature-256` check, which is off while it is unset.
4. Set `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`.
5. Set the Google variables above and `BUSINESS_CONFIG_FILE`.

```bash
uv run uvicorn bot.main:app --host 0.0.0.0 --port 8000
```

`bot/main.py` picks the real adapter for each side only when its variables are
present, so a half-configured environment falls back to the fakes -- except for
a declared calendar with no key, which is a misconfiguration and stops the boot.

Credentials come from `GOOGLE_CREDENTIALS_JSON` (the key itself, which is how
hosting platforms hand secrets over) or `GOOGLE_CREDENTIALS_FILE` (a path, for
local work). The first wins.

In a container:

```bash
docker build -t turnos-bot .
docker run -p 8000:8000 \
  -e TENANTS_FILE=/config/tenants.json \
  -e GOOGLE_CREDENTIALS_JSON="$(cat service-account.json)" \
  -v "$PWD/tenants.json:/config/tenants.json:ro" \
  turnos-bot
```

Known gaps, on purpose:

- Sessions live in memory. Move to Redis behind `SessionStorePort` before
  running more than one worker (which the calendar race also forbids).
- Days are offered without checking whether they have any slot left; a day with
  none answers with a message and sends the customer back.
- A calendar that cannot be read raises `CalendarUnavailable` and the customer
  gets no reply. It should get an apology instead.
- No reminder messages yet. Those are **template** messages: each one is billed
  and needs Meta's approval per WhatsApp Business Account.
