"""Azioni (servizi) di Home Assistant: utili per automazioni e, più avanti, Telegram."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .helpers import to_utc
from .manager import Manager

SERVICE_CREATE_QR = "create_qr"
SERVICE_REVOKE_QR = "revoke_qr"
SERVICE_RESTORE_QR = "restore_qr"
SERVICE_UPDATE_QR = "update_qr"
SERVICE_SIMULATE_SCAN = "simulate_scan"

CREATE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("valid_from"): vol.Any(None, cv.string),
        vol.Optional("valid_until"): vol.Any(None, cv.string),
        vol.Optional("max_uses", default=1): vol.All(vol.Coerce(int)),
        vol.Optional("unlimited", default=False): cv.boolean,
    }
)
REVOKE_SCHEMA = vol.Schema({vol.Required("id"): cv.string})
SIMULATE_SCHEMA = vol.Schema({vol.Required("code"): cv.string})
UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required("id"): cv.string,
        vol.Optional("valid_from"): vol.Any(None, cv.string),
        vol.Optional("valid_until"): vol.Any(None, cv.string),
        vol.Optional("uses_left"): vol.All(vol.Coerce(int)),
        vol.Optional("unlimited", default=False): cv.boolean,
    }
)


def _manager(hass: HomeAssistant) -> Manager:
    manager: Manager | None = hass.data.get(DOMAIN)
    if manager is None:
        raise HomeAssistantError("QR Guest Access non è configurato o non è ancora avviato.")
    return manager


async def _handle_create(call: ServiceCall) -> ServiceResponse:
    manager = _manager(call.hass)
    try:
        token = manager.engine.create_token(
            name=call.data["name"],
            valid_from=to_utc(call.data.get("valid_from")),
            valid_until=to_utc(call.data.get("valid_until")),
            # Se non dici nulla l'accesso è monouso: la scelta più prudente.
            # Gli accessi illimitati vanno richiesti esplicitamente.
            max_uses=None if call.data["unlimited"] else call.data["max_uses"],
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    return dict(token) if call.return_response else None


async def _handle_revoke(call: ServiceCall) -> None:
    if not _manager(call.hass).engine.revoke_token(call.data["id"]):
        raise ServiceValidationError("Token non trovato.")


async def _handle_restore(call: ServiceCall) -> None:
    if not _manager(call.hass).engine.restore_token(call.data["id"]):
        raise ServiceValidationError("Token non trovato o non revocato.")


async def _handle_update(call: ServiceCall) -> ServiceResponse:
    manager = _manager(call.hass)
    changes: dict = {}
    try:
        # I campi vuoti si ignorano: da un'automazione non si cancella per sbaglio una scadenza.
        if call.data.get("valid_from"):
            changes["valid_from"] = to_utc(call.data["valid_from"])
        if call.data.get("valid_until"):
            changes["valid_until"] = to_utc(call.data["valid_until"])
        if call.data["unlimited"]:
            changes["uses_left"] = None
        elif "uses_left" in call.data:
            changes["uses_left"] = call.data["uses_left"]
        token = manager.engine.update_token(call.data["id"], **changes)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    return dict(token) if call.return_response else None


async def _handle_simulate(call: ServiceCall) -> ServiceResponse:
    manager = _manager(call.hass)
    result = await manager.async_simulate(None, call.data["code"])
    if not call.return_response:
        return None
    return {"ignored": True} if result is None else result.as_dict()


def async_register_services(hass: HomeAssistant) -> None:
    """Registra le azioni (una sola volta, da async_setup)."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_QR,
        _handle_create,
        schema=CREATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REVOKE_QR, _handle_revoke, schema=REVOKE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESTORE_QR, _handle_restore, schema=REVOKE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_QR,
        _handle_update,
        schema=UPDATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIMULATE_SCAN,
        _handle_simulate,
        schema=SIMULATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
