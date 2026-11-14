"""Collante tra Home Assistant e il motore degli accessi."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_DOOR_ENTITY,
    CONF_OPEN_SECONDS,
    CONF_READER_ENTITY,
    DEFAULT_OPEN_SECONDS,
    EVENT_SCAN,
    EVENT_UPDATE,
    SIGNAL_UPDATE,
)
from .door import ShellyDoor
from .engine import SOURCE_CAMERA, SOURCE_SIMULATE, AccessEngine, ScanResult
from .qr_image import make_png
from .storage import QRStore

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class Manager:
    """Tiene insieme lettore QR, porta, storage e motore."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: QRStore,
        data: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.entry = entry
        config = {**entry.data, **entry.options}
        self.reader_entity: str = config[CONF_READER_ENTITY]
        self.door_entity: str = config[CONF_DOOR_ENTITY]
        self.camera_entity: str | None = config.get(CONF_CAMERA_ENTITY) or None
        open_seconds = int(config.get(CONF_OPEN_SECONDS, DEFAULT_OPEN_SECONDS))

        self._store = store
        self._door = ShellyDoor(hass, self.door_entity)
        self._unsubs: list[Callable[[], None]] = []
        self.engine = AccessEngine(
            data,
            door=self._door,
            clock=dt_util.utcnow,
            open_seconds=open_seconds,
            persist=store.schedule_save,
            on_event=self._on_event,
            on_change=self._on_change,
        )

    @classmethod
    async def async_create(cls, hass: HomeAssistant, entry: ConfigEntry) -> Manager:
        store = QRStore(hass)
        data = await store.async_load()
        return cls(hass, entry, store, data)

    # ------------------------------------------------------------------
    # Ciclo di vita
    # ------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Si mette in ascolto del lettore QR."""
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.reader_entity], self._handle_reader_event
            )
        )
        # Gli stati dei token cambiano con il tempo (in attesa -> attivo -> scaduto):
        # aggiorniamo i sensori ogni minuto.
        self._unsubs.append(
            async_track_time_interval(self.hass, self._periodic, timedelta(minutes=1))
        )
        _LOGGER.info(
            "In ascolto del lettore %s, porta %s (modalità test: %s)",
            self.reader_entity,
            self.door_entity,
            "attiva" if self.engine.test_mode else "disattiva",
        )

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._door.async_shutdown()
        await self._store.async_save_now(self.engine.snapshot())

    # ------------------------------------------------------------------
    # Lettore QR
    # ------------------------------------------------------------------

    @callback
    def _handle_reader_event(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        # old_state None = l'entità è appena stata creata (es. riavvio di HA):
        # non agiamo mai su uno stato "ereditato", la porta resta chiusa.
        if new_state is None or old_state is None:
            return
        code = new_state.state
        if code == old_state.state or code in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        self.hass.async_create_task(
            self._async_process_scan(code, SOURCE_CAMERA),
            name="qr_guest_access scan",
        )

    async def _async_process_scan(self, code: str, source: str) -> ScanResult | None:
        try:
            return await self.engine.handle_scan(code, source)
        except Exception:  # noqa: BLE001 - un errore qui non deve mai passare inosservato
            _LOGGER.exception("Errore durante la gestione di una scansione")
            return None

    async def async_simulate(self, token_id: str | None, code: str | None) -> ScanResult | None:
        """Scansione simulata: stessa procedura della telecamera."""
        if token_id:
            code = self.engine.token_secret(token_id)
            if code is None:
                raise ValueError("Token non trovato.")
        if not code:
            raise ValueError("Indica un token o un testo da simulare.")
        return await self._async_process_scan(code, SOURCE_SIMULATE)

    # ------------------------------------------------------------------
    # Immagini QR
    # ------------------------------------------------------------------

    async def async_qr_png(self, token_id: str) -> tuple[str, bytes]:
        """Restituisce (nome file, PNG) del QR di un token."""
        secret = self.engine.token_secret(token_id)
        if secret is None:
            raise ValueError("Token non trovato.")
        name = next(
            (t["name"] for t in self.engine.get_state()["tokens"] if t["id"] == token_id),
            "qr",
        )
        png = await self.hass.async_add_executor_job(make_png, secret)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "qr"
        return f"qr-{slug}.png", png

    # ------------------------------------------------------------------
    # Stato verso pannello e sensori
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        state = self.engine.get_state()
        state["entities"] = {
            "reader": self.reader_entity,
            "door": self.door_entity,
            "camera": self.camera_entity,
        }
        return state

    @callback
    def _on_event(self, entry: dict[str, Any]) -> None:
        """Evento utilizzabile nelle automazioni (mai con il token dentro)."""
        self.hass.bus.async_fire(
            EVENT_SCAN,
            {
                "name": entry["name"],
                "result": entry["result"],
                "door_opened": entry["door_opened"],
                "test": entry["test"],
                "source": entry["source"],
                "time": entry["ts"],
            },
        )

    @callback
    def _on_change(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
        self.hass.bus.async_fire(EVENT_UPDATE, {})

    @callback
    def _periodic(self, _now: datetime) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
