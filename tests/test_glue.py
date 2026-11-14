"""Test di collegamento con un Home Assistant FINTO.

Non sostituiscono una prova su HA vero, ma verificano che il codice di
collegamento (manager, porta, storage) sia coerente con sé stesso: nomi,
await, ordine delle chiamate. Sono il tipo di errore che la prima versione
del progetto nascondeva (es. "'NoneType' object can't be awaited").

Esecuzione:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "qr_guest_access"


# ----------------------------------------------------------------------------
# Finto Home Assistant (solo ciò che manager.py, door.py e storage.py usano)
# ----------------------------------------------------------------------------
class FakeState:
    def __init__(self, state: str) -> None:
        self.state = state


class FakeEvent:
    def __init__(self, data: dict) -> None:
        self.data = data


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_on: set[str] = set()

    async def async_call(self, domain, service, data=None, blocking=False):
        if service in self.fail_on:
            raise RuntimeError(f"{service} fallito")
        self.calls.append((domain, service, dict(data or {})))


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def async_fire(self, event_type, data=None):
        self.events.append((event_type, dict(data or {})))


class FakeHass:
    def __init__(self) -> None:
        self.services = FakeServices()
        self.bus = FakeBus()
        self.tasks: list[asyncio.Future] = []
        self.dispatches: list[str] = []
        self.listeners: list = []
        self.later: list = []
        self.notifications: list = []

    def async_create_task(self, coro, name=None):
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    async def settle(self):
        if self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()


HASS: FakeHass | None = None  # impostato in ogni test; usato dagli stub


def _install_stubs() -> None:
    def mod(name: str, **attrs) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module
        return module

    class Store:
        loaded: dict | None = None
        instances: list = []

        def __init__(self, hass, version, key):
            self.key, self.delayed, self.saved = key, None, None
            Store.instances.append(self)

        async def async_load(self):
            return Store.loaded

        def async_delay_save(self, func, delay=0):
            self.delayed = func

        async def async_save(self, data):
            self.saved = data

    def track_state(hass, entities, action):
        hass.listeners.append((list(entities), action))
        return lambda: hass.listeners.remove((list(entities), action))

    def track_interval(hass, action, interval):
        return lambda: None

    def call_later(hass, delay, action):
        item = (delay, action)
        hass.later.append(item)
        return lambda: hass.later.remove(item) if item in hass.later else None

    def dispatcher_send(hass, signal, *args):
        hass.dispatches.append(signal)

    def notify_create(hass, message, title=None, notification_id=None):
        hass.notifications.append((title, message, notification_id))

    ha = mod("homeassistant")
    mod("homeassistant.const", STATE_UNAVAILABLE="unavailable", STATE_UNKNOWN="unknown")
    mod("homeassistant.core", Event=FakeEvent, HomeAssistant=FakeHass, callback=lambda f: f)
    helpers = mod("homeassistant.helpers")
    helpers.dispatcher = mod("homeassistant.helpers.dispatcher", async_dispatcher_send=dispatcher_send)
    helpers.event = mod(
        "homeassistant.helpers.event",
        async_track_state_change_event=track_state,
        async_track_time_interval=track_interval,
        async_call_later=call_later,
    )
    helpers.storage = mod("homeassistant.helpers.storage", Store=Store)
    util = mod("homeassistant.util")
    util.dt = mod(
        "homeassistant.util.dt",
        utcnow=lambda: datetime.now(timezone.utc),
    )
    components = mod("homeassistant.components")
    components.persistent_notification = mod(
        "homeassistant.components.persistent_notification", async_create=notify_create
    )
    ha.const, ha.core, ha.helpers, ha.util, ha.components = (
        sys.modules["homeassistant.const"],
        sys.modules["homeassistant.core"],
        helpers,
        util,
        components,
    )
    sys.modules["__qr_store_cls__"] = types.ModuleType("__qr_store_cls__")
    sys.modules["__qr_store_cls__"].Store = Store


def _load_package() -> types.ModuleType:
    _install_stubs()
    root = types.ModuleType("custom_components")
    root.__path__ = [str(ROOT / "custom_components")]
    pkg = types.ModuleType("custom_components.qr_guest_access")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["custom_components"] = root
    sys.modules["custom_components.qr_guest_access"] = pkg
    return importlib.import_module("custom_components.qr_guest_access.manager")


manager_mod = _load_package()
Store = sys.modules["__qr_store_cls__"].Store
from custom_components.qr_guest_access.qr_image import QRImageError  # noqa: E402
from custom_components.qr_guest_access import door as door_mod  # noqa: E402


class FakeEntry:
    entry_id = "entry1"

    def __init__(self, **over) -> None:
        self.data = {
            "reader_entity": "image_processing.qr_porta",
            "door_entity": "switch.shelly1_porta",
            "camera_entity": "camera.porta",
            "open_seconds": 3,
        }
        self.data.update(over)
        self.options: dict = {}


class GlueTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Store.loaded = None
        Store.instances.clear()
        self.hass = FakeHass()
        self.manager = await manager_mod.Manager.async_create(self.hass, FakeEntry())
        self.manager.async_start()
        self.engine = self.manager.engine
        self.engine.set_test_mode(False)
        self.hass.services.calls.clear()
        self.hass.bus.events.clear()
        public = self.engine.create_token("Mario", None, None, 1)
        self.token_id = public["id"]
        self.secret = self.engine.token_secret(self.token_id)

    async def reader(self, old, new):
        """Simula il cambio di stato dell'entità del lettore QR."""
        _entities, action = self.hass.listeners[0]
        action(FakeEvent({
            "old_state": None if old is None else FakeState(old),
            "new_state": None if new is None else FakeState(new),
        }))
        await self.hass.settle()

    # -- il percorso principale -------------------------------------------------
    async def test_valid_qr_opens_door_then_closes_it(self):
        self.assertEqual(self.hass.listeners[0][0], ["image_processing.qr_porta"])
        await self.reader("unknown", self.secret)
        self.assertEqual(
            self.hass.services.calls,
            [("homeassistant", "turn_on", {"entity_id": "switch.shelly1_porta"})],
        )
        self.assertEqual(len(self.hass.later), 1)
        delay, turn_off = self.hass.later[0]
        self.assertEqual(delay, 3)
        await turn_off(None)  # scatta il timer
        self.assertEqual(self.hass.services.calls[-1][1], "turn_off")

    async def test_scan_event_for_automations_has_no_secret(self):
        await self.reader("unknown", self.secret)
        scan = [d for t, d in self.hass.bus.events if t == "qr_guest_access_scan"]
        self.assertEqual(len(scan), 1)
        self.assertEqual(scan[0]["result"], "granted")
        self.assertEqual(scan[0]["name"], "Mario")
        self.assertTrue(scan[0]["door_opened"])
        self.assertNotIn(self.secret, repr(self.hass.bus.events))
        self.assertIn("qr_guest_access_update", [t for t, _ in self.hass.bus.events])
        self.assertIn("qr_guest_access_signal_update", self.hass.dispatches)

    async def test_second_use_of_single_use_is_denied(self):
        await self.reader("unknown", self.secret)
        await self.reader("unknown", self.secret)  # ignorata dal cooldown
        self.assertEqual(len([c for c in self.hass.services.calls if c[1] == "turn_on"]), 1)
        sim = await self.manager.async_simulate(self.token_id, None)  # niente cooldown
        self.assertEqual(sim.result, "denied_exhausted")

    # -- stati del lettore che NON devono mai aprire --------------------------------
    async def test_ignored_reader_states(self):
        await self.reader(None, self.secret)  # entità appena creata (riavvio di HA)
        await self.reader("unknown", "unknown")
        await self.reader("unknown", "unavailable")
        await self.reader(self.secret, self.secret)  # nessuna variazione
        await self.reader("unknown", None)  # entità rimossa
        self.assertEqual(self.hass.services.calls, [])
        self.assertEqual(self.engine.get_state()["logs"], [])

    async def test_unknown_qr_is_logged_not_opened(self):
        await self.reader("unknown", "https://example.com/promo")
        self.assertEqual(self.hass.services.calls, [])
        log = self.engine.get_state()["logs"][0]
        self.assertEqual(log["result"], "denied_unknown")
        self.assertEqual(log["source"], "camera")

    async def test_test_mode_does_not_touch_the_door(self):
        self.engine.set_test_mode(True)
        await self.reader("unknown", self.secret)
        self.assertEqual(self.hass.services.calls, [])
        self.assertTrue(self.engine.get_state()["logs"][0]["test"])

    # -- guasti della porta ---------------------------------------------------------
    async def test_turn_on_failure_is_logged_and_access_refunded(self):
        self.hass.services.fail_on = {"turn_on"}
        await self.reader("unknown", self.secret)
        self.assertEqual(self.hass.later, [])
        state = self.engine.get_state()
        self.assertEqual(state["logs"][0]["result"], "error")
        self.assertEqual(state["tokens"][0]["uses_left"], 1)

    async def test_turn_off_failure_raises_a_notification(self):
        await self.reader("unknown", self.secret)
        self.hass.services.fail_on = {"turn_off"}
        door_mod.TURN_OFF_RETRY_DELAY = 0
        await self.hass.later[0][1](None)
        self.assertEqual(len(self.hass.notifications), 1)
        self.assertEqual(self.hass.notifications[0][2], "qr_guest_access_door_stuck")

    async def test_second_valid_open_restarts_the_timer(self):
        other = self.engine.create_token("Anna", None, None, 2)
        other_secret = self.engine.token_secret(other["id"])
        await self.reader("unknown", self.secret)
        await self.reader("unknown", other_secret)
        self.assertEqual(len(self.hass.later), 1)  # un solo timer: il vecchio è stato annullato

    # -- ciclo di vita ---------------------------------------------------------------
    async def test_shutdown_closes_open_door_and_saves(self):
        await self.reader("unknown", self.secret)
        self.hass.services.calls.clear()
        await self.manager.async_shutdown()
        self.assertEqual(self.hass.services.calls[-1][1], "turn_off")
        self.assertEqual(self.hass.listeners, [])
        saved = Store.instances[0].saved
        self.assertEqual(saved["tokens"][self.token_id]["uses_left"], 0)

    async def test_data_survives_a_restart(self):
        await self.reader("unknown", self.secret)
        Store.loaded = Store.instances[0].delayed()  # ciò che HA avrebbe scritto su disco
        restarted = await manager_mod.Manager.async_create(self.hass, FakeEntry())
        self.assertEqual(restarted.engine.get_state()["tokens"][0]["name"], "Mario")
        self.assertEqual(restarted.engine.stats()["granted"], 1)

    async def test_storage_key_is_the_new_one(self):
        self.assertEqual(Store.instances[0].key, "qr_guest_access_v2")

    async def test_options_override_entry_data(self):
        entry = FakeEntry()
        entry.options = {"open_seconds": 8, "door_entity": "switch.altra"}
        manager = await manager_mod.Manager.async_create(self.hass, entry)
        self.assertEqual(manager.engine.open_seconds, 8)
        self.assertEqual(manager.door_entity, "switch.altra")

    async def test_camera_is_optional(self):
        entry = FakeEntry(camera_entity=None)
        manager = await manager_mod.Manager.async_create(self.hass, entry)
        self.assertIsNone(manager.get_state()["entities"]["camera"])

    # -- pannello --------------------------------------------------------------------
    async def test_state_for_panel_never_contains_the_secret(self):
        state = self.manager.get_state()
        self.assertNotIn(self.secret, repr(state))
        self.assertEqual(state["entities"]["door"], "switch.shelly1_porta")

    async def test_qr_png(self):
        try:
            filename, png = await self.manager.async_qr_png(self.token_id)
        except QRImageError as err:
            self.skipTest(f"segno non disponibile qui ({err}): verificato solo il messaggio d'errore")
        self.assertEqual(filename, "qr-mario.png")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    async def test_qr_png_unknown_id(self):
        with self.assertRaises(ValueError):
            await self.manager.async_qr_png("nope")

    async def test_simulate_validation(self):
        with self.assertRaises(ValueError):
            await self.manager.async_simulate(None, None)
        with self.assertRaises(ValueError):
            await self.manager.async_simulate("nope", None)


if __name__ == "__main__":
    unittest.main()
