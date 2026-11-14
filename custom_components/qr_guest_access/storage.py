"""Persistenza su .storage di Home Assistant."""
from __future__ import annotations

from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import SAVE_DELAY, STORAGE_KEY, STORAGE_VERSION


class QRStore:
    """Sottile adattatore sopra Store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> dict[str, Any]:
        return await self._store.async_load() or {}

    def schedule_save(self, data_func: Callable[[], dict[str, Any]]) -> None:
        """Salvataggio differito (raggruppa più modifiche ravvicinate)."""
        self._store.async_delay_save(data_func, SAVE_DELAY)

    async def async_save_now(self, data: dict[str, Any]) -> None:
        await self._store.async_save(data)
