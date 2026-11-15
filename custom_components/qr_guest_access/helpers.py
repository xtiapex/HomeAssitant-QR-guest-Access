"""Funzioni di supporto condivise da pannello (WebSocket) e servizi."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util


def to_utc(value: Any) -> datetime | None:
    """Converte stringhe/datetime in datetime UTC.

    Le date senza fuso orario (come quelle del selettore data/ora di HA) sono
    interpretate nel fuso orario configurato in Home Assistant.
    Solleva ValueError (messaggio in italiano) se non valide.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = dt_util.parse_datetime(str(value))
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValueError(f"Data non valida: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(parsed)


_RESULT_TEXT = {
    "denied_unknown": "QR sconosciuto",
    "denied_revoked": "QR revocato",
    "denied_expired": "QR scaduto",
    "denied_not_started": "QR non ancora valido",
    "denied_exhausted": "QR con accessi esauriti",
    "denied_no_door": "QR senza porte abilitate",
}


def notification_text(entry: dict[str, Any]) -> tuple[str, str]:
    """(titolo, messaggio) della notifica per una voce dello storico."""
    name = entry.get("name") or "Sconosciuto"
    doors = ", ".join(entry.get("doors") or [])
    result = entry["result"]
    if result == "granted":
        failed = ", ".join(entry.get("doors_failed") or [])
        text = f"{name} ha aperto: {doors}" if doors else f"{name} è entrato"
        if failed:
            text += f" (non si è aperta: {failed})"
        return "Accesso consentito", text
    if result == "error":
        return "Porta non aperta", f"{name}: il relè non ha risposto ({', '.join(entry.get('doors_failed') or [])})"
    reason = _RESULT_TEXT.get(result, "Accesso negato")
    return "Accesso negato", f"{reason}" + (f": {name}" if entry.get("name") else "")
