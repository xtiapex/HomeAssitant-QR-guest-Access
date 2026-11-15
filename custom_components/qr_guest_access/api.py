"""Comandi WebSocket usati dal pannello. Tutti riservati agli amministratori."""
from __future__ import annotations

import base64
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .helpers import to_utc
from .manager import Manager
from .qr_image import QRImageError


def _get_manager(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> Manager | None:
    manager: Manager | None = hass.data.get(DOMAIN)
    if manager is None:
        connection.send_error(
            msg["id"], "not_loaded", "QR Guest Access non è configurato o non è ancora avviato."
        )
    return manager


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "qr_guest_access/state"})
@callback
def ws_state(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    connection.send_result(msg["id"], manager.get_state())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/create",
        vol.Required("name"): str,
        vol.Optional("valid_from"): vol.Any(str, None),
        vol.Optional("valid_until"): vol.Any(str, None),
        vol.Optional("max_uses"): vol.Any(int, None),
    }
)
@websocket_api.async_response
async def ws_create(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        token = manager.engine.create_token(
            name=msg["name"],
            valid_from=to_utc(msg.get("valid_from")),
            valid_until=to_utc(msg.get("valid_until")),
            max_uses=msg.get("max_uses"),
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return

    # Il token esiste già: se il QR non si riesce a disegnare lo diciamo, ma non lo perdiamo.
    result: dict[str, Any] = {"token": token, "filename": None, "png_base64": None, "qr_error": None}
    try:
        filename, png = await manager.async_qr_png(token["id"])
        result["filename"] = filename
        result["png_base64"] = base64.b64encode(png).decode("ascii")
    except (QRImageError, ValueError) as err:
        result["qr_error"] = str(err)
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "qr_guest_access/qr", vol.Required("token_id"): str}
)
@websocket_api.async_response
async def ws_qr(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        filename, png = await manager.async_qr_png(msg["token_id"])
    except ValueError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    except QRImageError as err:
        connection.send_error(msg["id"], "qr_failed", str(err))
        return
    connection.send_result(
        msg["id"],
        {"filename": filename, "png_base64": base64.b64encode(png).decode("ascii")},
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "qr_guest_access/revoke", vol.Required("token_id"): str}
)
@callback
def ws_revoke(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    if not manager.engine.revoke_token(msg["token_id"]):
        connection.send_error(msg["id"], "not_found", "Token non trovato.")
        return
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "qr_guest_access/delete", vol.Required("token_id"): str}
)
@callback
def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    if not manager.engine.delete_token(msg["token_id"]):
        connection.send_error(msg["id"], "not_found", "Token non trovato.")
        return
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/simulate",
        vol.Optional("token_id"): vol.Any(str, None),
        vol.Optional("code"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_simulate(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        result = await manager.async_simulate(msg.get("token_id"), msg.get("code"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(
        msg["id"], {"ignored": True} if result is None else result.as_dict()
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "qr_guest_access/set_test_mode", vol.Required("enabled"): bool}
)
@callback
def ws_set_test_mode(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    manager.engine.set_test_mode(msg["enabled"])
    connection.send_result(msg["id"], {"test_mode": manager.engine.test_mode})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "qr_guest_access/clear_logs"})
@callback
def ws_clear_logs(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    manager.engine.clear_logs()
    connection.send_result(msg["id"], {})


def async_register_api(hass: HomeAssistant) -> None:
    """Registra i comandi (una sola volta, da async_setup)."""
    for command in (
        ws_state,
        ws_create,
        ws_qr,
        ws_revoke,
        ws_delete,
        ws_simulate,
        ws_set_test_mode,
        ws_clear_logs,
    ):
        websocket_api.async_register_command(hass, command)
