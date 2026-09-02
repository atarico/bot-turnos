"""Every string the customer reads, in one place.

Kept apart from the flow on purpose: re-voicing the bot for another business
(or another country's Spanish) must never mean editing the state machine.
Current register: Rioplatense, informal.
"""

from __future__ import annotations

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

GREETING = "¡Hola! Soy el asistente de {business}.\n¿Qué necesitás?"
BTN_BOOK = "Sacar turno"
BTN_MINE = "Mis turnos"
BTN_CANCEL = "Cancelar turno"

ASK_SERVICE = "¿Qué servicio querés reservar?"
ASK_SERVICE_ACTION = "Ver servicios"
ASK_DAY = "¿Para qué día lo querés?"
ASK_DAY_ACTION = "Ver días"
ASK_TIME = "Horarios libres para el {day}:"
ASK_TIME_ACTION = "Ver horarios"
MORE_ROW = "Ver más opciones"

CONFIRM = "¿Confirmás este turno?\n\n{service}\n{day} a las {time}"
BTN_CONFIRM_YES = "Sí, confirmar"
BTN_CONFIRM_NO = "No, volver"

BOOKED = "¡Listo! Tu turno quedó reservado.\n\n{service}\n{day} a las {time}\n\nTe esperamos en {business}."
SLOT_TAKEN = "Uy, ese horario ya no está disponible — lo reservaron recién. Probá con otro."
NO_SLOTS = "No quedan horarios libres para ese día. Probá con otro."

MINE_EMPTY = "No tenés turnos reservados."
MINE_LIST = "Tus próximos turnos:\n\n{lines}"
MINE_LINE = "• {service} — {day} a las {time}"

CANCEL_EMPTY = "No tenés turnos para cancelar."
CANCEL_ASK = "¿Cuál querés cancelar?"
CANCEL_ACTION = "Ver turnos"
CANCEL_CONFIRM = "¿Seguro que querés cancelar este turno?\n\n{service}\n{day} a las {time}"
BTN_CANCEL_YES = "Sí, cancelar"
BTN_CANCEL_NO = "No, dejarlo"
CANCELLED = "Tu turno fue cancelado. Cuando quieras sacás otro."
