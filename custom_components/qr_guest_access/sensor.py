"""Sensori di QR Guest Access (utili per dashboard e automazioni)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATE
from .manager import Manager


@dataclass(frozen=True, kw_only=True)
class QRSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Manager], Any]
    attrs_fn: Callable[[Manager], dict[str, Any]] | None = None


def _last_access_time(manager: Manager) -> datetime | None:
    last = manager.engine.last_log()
    return dt_util.parse_datetime(last["ts"]) if last else None


def _last_access_attrs(manager: Manager) -> dict[str, Any]:
    last = manager.engine.last_log()
    if not last:
        return {}
    return {
        "name": last["name"],
        "result": last["result"],
        "door_opened": last["door_opened"],
        "doors": last.get("doors", []),
        "test": last["test"],
        "source": last["source"],
    }


SENSORS: tuple[QRSensorDescription, ...] = (
    QRSensorDescription(
        key="active_tokens",
        translation_key="active_tokens",
        icon="mdi:qrcode",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m: m.engine.stats()["active"],
        attrs_fn=lambda m: {
            "pending": m.engine.stats()["pending"],
            "total": m.engine.stats()["total"],
            "test_mode": m.engine.test_mode,
        },
    ),
    QRSensorDescription(
        key="granted",
        translation_key="granted",
        icon="mdi:door-open",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda m: m.engine.stats()["granted"],
    ),
    QRSensorDescription(
        key="denied",
        translation_key="denied",
        icon="mdi:door-closed-lock",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda m: m.engine.stats()["denied"],
    ),
    QRSensorDescription(
        key="last_access",
        translation_key="last_access",
        icon="mdi:history",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_access_time,
        attrs_fn=_last_access_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: Manager = hass.data[DOMAIN]
    async_add_entities(QRSensor(manager, entry, description) for description in SENSORS)


class QRSensor(SensorEntity):
    """Sensore aggiornato a eventi (nessun polling)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: QRSensorDescription

    def __init__(self, manager: Manager, entry: ConfigEntry, description: QRSensorDescription) -> None:
        self._manager = manager
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="QR Guest Access",
            manufacturer="QR Guest Access",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._manager)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self._manager) if fn else None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
