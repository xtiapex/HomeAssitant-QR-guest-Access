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
