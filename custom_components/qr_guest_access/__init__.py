"""QR Guest Access: apertura porta con QR code temporanei."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import async_register_api
from .const import (
    CONF_DOOR_ENTITY,
    CONF_READER_ENTITY,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_URL_PATH,
    PLATFORMS,
    STATIC_URL,
    VERSION,
)
from .manager import Manager
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_STATIC_REGISTERED = f"{DOMAIN}_static_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Comandi del pannello e azioni si registrano una volta sola, qui."""
    async_register_api(hass)
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    config = {**entry.data, **entry.options}
    if CONF_READER_ENTITY not in config or CONF_DOOR_ENTITY not in config:
        # Succede se è rimasta la configurazione della prima versione del progetto.
        raise ConfigEntryError(
            "Configurazione di una versione precedente: elimina l'integrazione "
            "'QR Guest Access' da Dispositivi e servizi e aggiungila di nuovo."
        )

    manager = await Manager.async_create(hass, entry)
    manager.async_start()
    hass.data[DOMAIN] = manager

    await _async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    manager: Manager | None = hass.data.pop(DOMAIN, None)
    if manager is not None:
        await manager.async_shutdown()
    try:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    except Exception:  # noqa: BLE001 - il pannello verrà comunque ri-registrato
        _LOGGER.debug("Rimozione del pannello non riuscita", exc_info=True)
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve panel.js e aggiunge "Accessi ospiti" alla barra laterale (solo admin)."""
    if not hass.data.get(_STATIC_REGISTERED):
        frontend_dir = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(frontend_dir), False)]
        )
        hass.data[_STATIC_REGISTERED] = True

    try:
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name=PANEL_ELEMENT,
            frontend_url_path=PANEL_URL_PATH,
            # ?v=... forza il browser a ricaricare il file dopo un aggiornamento
            module_url=f"{STATIC_URL}/panel.js?v={VERSION}",
            sidebar_title="Accessi ospiti",
            sidebar_icon="mdi:qrcode",
            require_admin=True,
            config={},
        )
    except ValueError:
        _LOGGER.debug("Il pannello %s era già registrato", PANEL_URL_PATH)
