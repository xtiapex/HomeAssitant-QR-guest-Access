"""Configurazione guidata di QR Guest Access."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_DOOR_ENTITY,
    CONF_OPEN_SECONDS,
    CONF_READER_ENTITY,
    DEFAULT_OPEN_SECONDS,
    DOMAIN,
)


def _schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_READER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="image_processing")
            ),
            vol.Required(CONF_DOOR_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["switch", "light", "input_boolean"])
            ),
            vol.Optional(CONF_CAMERA_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="camera")
            ),
            vol.Required(CONF_OPEN_SECONDS, default=DEFAULT_OPEN_SECONDS): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=30,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_OPEN_SECONDS] = int(data[CONF_OPEN_SECONDS])
    # Un campo opzionale lasciato vuoto non compare in user_input: lo rendiamo esplicito.
    data[CONF_CAMERA_ENTITY] = data.get(CONF_CAMERA_ENTITY) or None
    return data


class QRGuestAccessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Procedura di prima configurazione."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="QR Guest Access", data=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema())
