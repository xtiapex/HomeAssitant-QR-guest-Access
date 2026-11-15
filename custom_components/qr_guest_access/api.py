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
        vol.Optional("doors"): vol.Any([str], None),
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
            doors=msg.get("doors"),
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
    {vol.Required("type"): "qr_guest_access/restore", vol.Required("token_id"): str}
)
@callback
def ws_restore(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    if not manager.engine.restore_token(msg["token_id"]):
        connection.send_error(msg["id"], "not_found", "Token non trovato o non revocato.")
        return
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/update",
        vol.Required("token_id"): str,
        vol.Optional("valid_from"): vol.Any(str, None),
        vol.Optional("valid_until"): vol.Any(str, None),
        vol.Optional("uses_left"): vol.Any(int, None),
        vol.Optional("doors"): vol.Any([str], None),
    }
)
@callback
def ws_update(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    changes: dict[str, Any] = {}
    try:
        if "valid_from" in msg:
            changes["valid_from"] = to_utc(msg["valid_from"])
        if "valid_until" in msg:
            changes["valid_until"] = to_utc(msg["valid_until"])
        if "uses_left" in msg:
            changes["uses_left"] = msg["uses_left"]
        if "doors" in msg:
            changes["doors"] = msg["doors"]
        token = manager.engine.update_token(msg["token_id"], **changes)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"token": token})


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


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/logs",
        vol.Optional("query"): vol.Any(str, None),
        vol.Optional("limit", default=200): vol.All(int, vol.Range(min=1, max=500)),
    }
)
@callback
def ws_logs(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Ricerca nello storico (fino a 500 voci), per nome, porta o codice."""
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    connection.send_result(
        msg["id"], {"logs": manager.engine.search_logs(msg.get("query"), msg["limit"])}
    )


def _check_entity(hass: HomeAssistant, entity_id: str | None, label: str) -> None:
    if entity_id and hass.states.get(entity_id) is None:
        raise ValueError(f"{label}: l'entità {entity_id} non esiste in Home Assistant.")


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/door_add",
        vol.Required("name"): str,
        vol.Required("door_entity"): str,
        vol.Required("open_seconds"): int,
    }
)
@callback
def ws_door_add(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        _check_entity(hass, msg["door_entity"], "Relè")
        door = manager.engine.add_door(msg["name"], msg["door_entity"], msg["open_seconds"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"door": door})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/door_update",
        vol.Required("door_id"): str,
        vol.Required("name"): str,
        vol.Required("door_entity"): str,
        vol.Required("open_seconds"): int,
    }
)
@callback
def ws_door_update(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        _check_entity(hass, msg["door_entity"], "Relè")
        door = manager.engine.update_door(
            msg["door_id"], msg["name"], msg["door_entity"], msg["open_seconds"]
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"door": door})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "qr_guest_access/door_delete", vol.Required("door_id"): str}
)
@callback
def ws_door_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        manager.engine.delete_door(msg["door_id"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/set_reader",
        vol.Required("reader_entity"): str,
        vol.Optional("camera_entity"): vol.Any(str, None),
    }
)
@callback
def ws_set_reader(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        _check_entity(hass, msg["reader_entity"], "Lettore")
        _check_entity(hass, msg.get("camera_entity"), "Telecamera")
        manager.engine.set_reader(msg["reader_entity"], msg.get("camera_entity"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "qr_guest_access/set_notify",
        vol.Required("services"): [str],
        vol.Required("on_granted"): bool,
        vol.Required("on_denied"): bool,
    }
)
@callback
def ws_set_notify(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        settings = manager.engine.set_notify(msg["services"], msg["on_granted"], msg["on_denied"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"notify": settings})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "qr_guest_access/test_notify"})
@websocket_api.async_response
async def ws_test_notify(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (manager := _get_manager(hass, connection, msg)) is None:
        return
    try:
        failed = await manager.async_test_notify()
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"failed": failed})


def async_register_api(hass: HomeAssistant) -> None:
    """Registra i comandi (una sola volta, da async_setup)."""
    for command in (
        ws_state,
        ws_create,
        ws_qr,
        ws_revoke,
        ws_restore,
        ws_update,
        ws_delete,
        ws_simulate,
        ws_set_test_mode,
        ws_clear_logs,
        ws_logs,
        ws_door_add,
        ws_door_update,
        ws_door_delete,
        ws_set_reader,
        ws_set_notify,
        ws_test_notify,
    ):
        websocket_api.async_register_command(hass, command)
