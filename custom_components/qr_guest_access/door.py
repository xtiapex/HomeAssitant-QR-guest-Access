"""Apertura della porta tramite l'entità della Shelly 1."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

TURN_OFF_ATTEMPTS = 3
TURN_OFF_RETRY_DELAY = 1.0


class ShellyDoor:
    """Accende il relè e lo spegne dopo N secondi.

    open() ritorna subito dopo l'accensione: lo spegnimento è programmato in
    background. Se arriva un'altra apertura mentre il relè è acceso, il timer
    riparte da capo. Consiglio comunque di impostare anche l'auto-spegnimento
    sulla Shelly stessa: è la rete di sicurezza se HA si blocca.
    """

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._cancel_off: Callable[[], None] | None = None
        self._is_on = False

    async def open(self, seconds: float) -> None:
        self._cancel_timer()
        await self._hass.services.async_call(
            "homeassistant",
            "turn_on",
            {"entity_id": self._entity_id},
            blocking=True,
        )
        self._is_on = True
        self._cancel_off = async_call_later(self._hass, seconds, self._async_turn_off)

    def _cancel_timer(self) -> None:
        if self._cancel_off is not None:
            self._cancel_off()
            self._cancel_off = None

    async def _async_turn_off(self, _now: datetime | None = None) -> None:
        self._cancel_off = None
        for attempt in range(1, TURN_OFF_ATTEMPTS + 1):
            try:
                await self._hass.services.async_call(
                    "homeassistant",
                    "turn_off",
                    {"entity_id": self._entity_id},
                    blocking=True,
                )
                self._is_on = False
                return
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Spegnimento di %s fallito (tentativo %d/%d)",
                    self._entity_id,
                    attempt,
                    TURN_OFF_ATTEMPTS,
                )
                if attempt < TURN_OFF_ATTEMPTS:
                    await asyncio.sleep(TURN_OFF_RETRY_DELAY)

        persistent_notification.async_create(
            self._hass,
            f"Non sono riuscito a richiudere {self._entity_id}. "
            "Controlla la porta e spegni il relè a mano.",
            title="QR Guest Access: porta forse aperta",
            notification_id="qr_guest_access_door_stuck",
        )

    async def async_shutdown(self) -> None:
        """Richiude subito se il relè è acceso (ricarica/arresto dell'integrazione)."""
        self._cancel_timer()
        if self._is_on:
            await self._async_turn_off()
