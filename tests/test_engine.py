"""Test del motore di validazione (non richiedono Home Assistant).

Esecuzione:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "qr_guest_access"
    / "engine.py"
)
_spec = importlib.util.spec_from_file_location("qr_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
sys.modules["qr_engine"] = engine
_spec.loader.exec_module(engine)

T0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class FakeDoor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self.fail = False
        self.fail_ids: set[str] = set()

    async def open(self, door_id: str, seconds: float) -> None:
        if self.fail or door_id in self.fail_ids:
            raise RuntimeError("relè irraggiungibile")
        self.calls.append((door_id, seconds))


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.door = FakeDoor()
        self.saved: list[dict] = []
        self.events: list[dict] = []
        self.changes = 0
        self.reader_changes = 0
        self.eng = self.make_engine({})
        self.eng.set_test_mode(False)
        self.gate = self.eng.add_door("Cancello", "switch.cancello", 3)

    def make_engine(self, data) -> "engine.AccessEngine":
        return engine.AccessEngine(
            data,
            self.door,
            self.clock,
            on_reader_changed=self._count_reader,
            persist=lambda func: self.saved.append(func()),
            on_event=self.events.append,
            on_change=self._count_change,
        )

    def _count_change(self) -> None:
        self.changes += 1

    def _count_reader(self) -> None:
        self.reader_changes += 1

    def token(self, **kw):
        params = dict(name="Mario", valid_from=None, valid_until=None, max_uses=1)
        params.update(kw)
        public = self.eng.create_token(**params)
        return public, self.eng.token_secret(public["id"])

    async def scan(self, code, source=engine.SOURCE_SIMULATE):
        return await self.eng.handle_scan(code, source)


class TestCreateValidation(Base):
    def test_defaults_and_token_format(self):
        public, secret = self.token()
        self.assertTrue(secret.startswith("QG-"))
        self.assertGreaterEqual(len(secret), 30)
        self.assertNotIn("Mario", secret)
        self.assertNotIn("token", public)  # il segreto non esce mai dalla vista pubblica
        self.assertEqual(public["status"], engine.STATUS_ACTIVE)
        self.assertEqual(public["uses_left"], 1)

    def test_tokens_are_unique(self):
        secrets_seen = {self.token(name=f"g{i}")[1] for i in range(200)}
        self.assertEqual(len(secrets_seen), 200)

    def test_empty_name(self):
        with self.assertRaises(ValueError):
            self.token(name="   ")

    def test_name_too_long(self):
        with self.assertRaises(ValueError):
            self.token(name="x" * 61)

    def test_end_before_start(self):
        with self.assertRaises(ValueError):
            self.token(
                valid_from=T0 + timedelta(days=2),
                valid_until=T0 + timedelta(days=1),
            )

    def test_end_in_the_past(self):
        with self.assertRaises(ValueError):
            self.token(valid_until=T0 - timedelta(minutes=1))

    def test_unlimited_requires_end_date(self):
        with self.assertRaises(ValueError):
            self.token(max_uses=None, valid_until=None)

    def test_max_uses_bounds(self):
        for bad in (0, -1, 1000, 2.5, True, "3"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.token(max_uses=bad)


class TestScanRules(Base):
    async def test_single_use(self):
        _, code = self.token(max_uses=1)
        first = await self.scan(code)
        self.assertEqual(first.result, engine.RESULT_GRANTED)
        self.assertTrue(first.door_opened)
        second = await self.scan(code)
        self.assertEqual(second.result, engine.RESULT_EXHAUSTED)
        self.assertEqual(self.door.calls, [(self.gate['id'], 3)])

    async def test_multi_use(self):
        _, code = self.token(max_uses=3)
        results = [(await self.scan(code)).result for _ in range(4)]
        self.assertEqual(results, [engine.RESULT_GRANTED] * 3 + [engine.RESULT_EXHAUSTED])
        self.assertEqual(len(self.door.calls), 3)

    async def test_unlimited_until_expiry(self):
        _, code = self.token(max_uses=None, valid_until=T0 + timedelta(days=1))
        for _ in range(10):
            self.assertEqual((await self.scan(code)).result, engine.RESULT_GRANTED)
        self.clock.advance(days=1, seconds=1)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_EXPIRED)
        self.assertEqual(len(self.door.calls), 10)

    async def test_not_started_yet(self):
        _, code = self.token(valid_from=T0 + timedelta(hours=2), max_uses=2)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_NOT_STARTED)
        self.clock.advance(hours=2, seconds=1)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_GRANTED)

    async def test_expired_with_uses_left(self):
        _, code = self.token(max_uses=5, valid_until=T0 + timedelta(hours=1))
        self.clock.advance(hours=2)
        result = await self.scan(code)
        self.assertEqual(result.result, engine.RESULT_EXPIRED)
        self.assertFalse(result.door_opened)
        self.assertEqual(self.door.calls, [])

    async def test_revoked(self):
        public, code = self.token(max_uses=5)
        self.assertTrue(self.eng.revoke_token(public["id"]))
        result = await self.scan(code)
        self.assertEqual(result.result, engine.RESULT_REVOKED)
        self.assertEqual(self.door.calls, [])
        self.assertFalse(self.eng.revoke_token("nonexistent"))

    async def test_unknown_code_logged_without_full_code(self):
        secret_like = "QG-" + "A" * 40
        result = await self.scan(secret_like)
        self.assertEqual(result.result, engine.RESULT_UNKNOWN)
        self.assertFalse(result.door_opened)
        entry = self.eng.get_state()["logs"][0]
        self.assertIsNone(entry["name"])
        self.assertLessEqual(len(entry["code"]), engine.CODE_PREVIEW_LEN + 1)
        self.assertNotIn("A" * 20, json.dumps(entry))
        self.assertEqual(self.door.calls, [])

    async def test_nothing_read_is_ignored(self):
        for value in (None, "", "  ", "unknown", "Unavailable", "None"):
            self.assertIsNone(await self.scan(value))
        self.assertEqual(self.eng.get_state()["logs"], [])

    async def test_deleted_token_becomes_unknown(self):
        public, code = self.token()
        self.assertTrue(self.eng.delete_token(public["id"]))
        self.assertEqual((await self.scan(code)).result, engine.RESULT_UNKNOWN)

    async def test_oversized_code_is_unknown(self):
        result = await self.scan("x" * 5000)
        self.assertEqual(result.result, engine.RESULT_UNKNOWN)
        self.assertLess(len(json.dumps(self.eng.get_state()["logs"][0])), 400)


class TestRestore(Base):
    async def test_restore_revoked_token_works_again(self):
        public, code = self.token(max_uses=3)
        await self.scan(code)  # 2 rimasti
        self.eng.revoke_token(public["id"])
        self.assertEqual((await self.scan(code)).result, engine.RESULT_REVOKED)
        self.assertTrue(self.eng.restore_token(public["id"]))
        state = {t["id"]: t for t in self.eng.get_state()["tokens"]}[public["id"]]
        self.assertEqual(state["status"], engine.STATUS_ACTIVE)
        self.assertEqual(state["uses_left"], 2)  # gli accessi non vengono ridati né tolti
        self.assertEqual((await self.scan(code)).result, engine.RESULT_GRANTED)

    def test_restore_unknown_or_not_revoked_is_refused(self):
        public, _ = self.token()
        self.assertFalse(self.eng.restore_token("nope"))
        self.assertFalse(self.eng.restore_token(public["id"]))  # non era revocato

    async def test_restored_token_that_expired_stays_expired(self):
        public, code = self.token(max_uses=5, valid_until=T0 + timedelta(hours=1))
        self.eng.revoke_token(public["id"])
        self.clock.advance(hours=2)
        self.assertTrue(self.eng.restore_token(public["id"]))
        self.assertEqual((await self.scan(code)).result, engine.RESULT_EXPIRED)

    async def test_restored_exhausted_token_stays_exhausted(self):
        public, code = self.token(max_uses=1)
        await self.scan(code)
        self.eng.revoke_token(public["id"])
        self.assertTrue(self.eng.restore_token(public["id"]))
        self.assertEqual((await self.scan(code)).result, engine.RESULT_EXHAUSTED)

    def test_restore_is_persisted(self):
        public, _ = self.token()
        self.eng.revoke_token(public["id"])
        self.eng.restore_token(public["id"])
        self.assertFalse(self.saved[-1]["tokens"][public["id"]]["revoked"])


class TestUpdate(Base):
    def view(self, token_id):
        return {t["id"]: t for t in self.eng.get_state()["tokens"]}[token_id]

    async def test_renew_exhausted_token_with_more_accesses(self):
        public, code = self.token(max_uses=1)
        await self.scan(code)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_EXHAUSTED)
        updated = self.eng.update_token(public["id"], uses_left=3)
        self.assertEqual((updated["uses_left"], updated["max_uses"], updated["uses_count"]), (3, 4, 1))
        self.assertEqual(updated["status"], engine.STATUS_ACTIVE)
        results = [(await self.scan(code)).result for _ in range(4)]
        self.assertEqual(results, [engine.RESULT_GRANTED] * 3 + [engine.RESULT_EXHAUSTED])

    async def test_extend_expired_token(self):
        public, code = self.token(max_uses=5, valid_until=T0 + timedelta(hours=1))
        self.clock.advance(hours=2)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_EXPIRED)
        self.eng.update_token(public["id"], valid_until=self.clock.now + timedelta(days=1))
        self.assertEqual((await self.scan(code)).result, engine.RESULT_GRANTED)

    async def test_move_start_date_later_makes_token_pending(self):
        public, code = self.token()
        self.eng.update_token(public["id"], valid_from=T0 + timedelta(hours=3))
        self.assertEqual(self.view(public["id"])["status"], engine.STATUS_PENDING)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_NOT_STARTED)

    def test_unspecified_fields_are_left_alone(self):
        public, _ = self.token(max_uses=4, valid_until=T0 + timedelta(days=2))
        before = self.view(public["id"])
        self.eng.update_token(public["id"], uses_left=2)
        after = self.view(public["id"])
        self.assertEqual((after["valid_from"], after["valid_until"]), (before["valid_from"], before["valid_until"]))
        self.assertEqual(after["uses_left"], 2)

    def test_valid_from_none_means_keep(self):
        public, _ = self.token(valid_from=T0 + timedelta(hours=1))
        before = self.view(public["id"])["valid_from"]
        self.eng.update_token(public["id"], valid_from=None, uses_left=2)
        self.assertEqual(self.view(public["id"])["valid_from"], before)

    def test_remove_end_date_for_limited_token(self):
        public, _ = self.token(max_uses=3, valid_until=T0 + timedelta(days=1))
        self.eng.update_token(public["id"], valid_until=None)
        self.assertIsNone(self.view(public["id"])["valid_until"])

    def test_switch_to_unlimited_requires_end_date(self):
        public, _ = self.token(max_uses=3, valid_until=None)
        with self.assertRaises(ValueError):
            self.eng.update_token(public["id"], uses_left=None)
        self.assertEqual(self.view(public["id"])["uses_left"], 3)  # nulla è cambiato
        updated = self.eng.update_token(public["id"], uses_left=None, valid_until=T0 + timedelta(days=1))
        self.assertIsNone(updated["max_uses"])
        self.assertIsNone(updated["uses_left"])

    def test_unlimited_back_to_limited_keeps_usage_count(self):
        public, _ = self.token(max_uses=None, valid_until=T0 + timedelta(days=1))
        self.eng._data["tokens"][public["id"]]["uses_count"] = 7
        updated = self.eng.update_token(public["id"], uses_left=2)
        self.assertEqual((updated["uses_left"], updated["max_uses"]), (2, 9))

    def test_invalid_changes_are_rejected_and_change_nothing(self):
        public, _ = self.token(max_uses=2, valid_until=T0 + timedelta(days=1))
        before = self.eng.snapshot()["tokens"][public["id"]]
        bad = [
            dict(uses_left=0), dict(uses_left=1000), dict(uses_left=True), dict(uses_left=1.5),
            dict(valid_until=T0 - timedelta(minutes=1)),            # già passata
            dict(valid_from=T0 + timedelta(days=2)),                # inizio dopo la fine attuale
            dict(valid_until=T0 - timedelta(days=5), valid_from=T0 - timedelta(days=9)),
        ]
        for changes in bad:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.eng.update_token(public["id"], **changes)
        self.assertEqual(self.eng.snapshot()["tokens"][public["id"]], before)

    def test_unknown_token(self):
        with self.assertRaises(ValueError):
            self.eng.update_token("nope", uses_left=2)

    async def test_editing_other_fields_of_an_expired_token_is_allowed(self):
        public, code = self.token(max_uses=2, valid_until=T0 + timedelta(hours=1))
        self.clock.advance(hours=3)  # ora è scaduto
        self.eng.update_token(public["id"], uses_left=5)  # la fine (passata) non cambia: nessun errore
        self.assertEqual(self.view(public["id"])["status"], engine.STATUS_EXPIRED)

    def test_revoked_token_stays_revoked_after_edit(self):
        public, _ = self.token(max_uses=1)
        self.eng.revoke_token(public["id"])
        self.eng.update_token(public["id"], uses_left=4)
        self.assertEqual(self.view(public["id"])["status"], engine.STATUS_REVOKED)

    def test_update_is_persisted_and_secret_not_exposed(self):
        public, code = self.token()
        updated = self.eng.update_token(public["id"], uses_left=6)
        self.assertEqual(self.saved[-1]["tokens"][public["id"]]["uses_left"], 6)
        self.assertNotIn("token", updated)
        self.assertEqual(self.eng.token_secret(public["id"]), code)  # il QR non cambia


class TestDoorAndModes(Base):
    async def test_door_failure_refunds_the_access(self):
        public, code = self.token(max_uses=2)
        self.door.fail = True
        failed = await self.scan(code)
        self.assertEqual(failed.result, engine.RESULT_ERROR)
        self.assertFalse(failed.door_opened)
        state = {t["id"]: t for t in self.eng.get_state()["tokens"]}[public["id"]]
        self.assertEqual(state["uses_left"], 2)
        self.assertEqual(state["uses_count"], 0)
        self.assertIsNone(state["last_used"])
        self.door.fail = False
        self.assertEqual((await self.scan(code)).result, engine.RESULT_GRANTED)

    async def test_test_mode_neither_opens_nor_consumes(self):
        _, code = self.token(max_uses=1)
        self.eng.set_test_mode(True)
        for _ in range(3):
            result = await self.scan(code)
            self.assertEqual(result.result, engine.RESULT_GRANTED)
            self.assertTrue(result.test)
            self.assertFalse(result.door_opened)
        self.assertEqual(self.door.calls, [])
        self.assertEqual(self.eng.stats()["granted"], 0)  # le prove non contano
        self.eng.set_test_mode(False)
        self.assertEqual((await self.scan(code)).result, engine.RESULT_GRANTED)
        self.assertEqual(len(self.door.calls), 1)

    def test_test_mode_is_default_on_fresh_install(self):
        fresh = self.make_engine({})
        self.assertTrue(fresh.test_mode)

    async def test_concurrent_scans_cannot_exceed_limit(self):
        import asyncio

        class SlowDoor(FakeDoor):
            async def open(self, door_id, seconds):
                await asyncio.sleep(0.01)
                await super().open(door_id, seconds)

        self.door = SlowDoor()
        self.eng = self.make_engine({})
        self.eng.set_test_mode(False)
        self.eng.add_door("Cancello", "switch.cancello", 3)
        _, code = self.token(max_uses=1)
        results = await asyncio.gather(*(self.scan(code) for _ in range(5)))
        granted = [r for r in results if r.result == engine.RESULT_GRANTED]
        self.assertEqual(len(granted), 1)
        self.assertEqual(len(self.door.calls), 1)


class TestCameraCooldown(Base):
    async def test_same_code_within_cooldown_is_ignored(self):
        _, code = self.token(max_uses=5)
        self.assertEqual((await self.scan(code, engine.SOURCE_CAMERA)).result, engine.RESULT_GRANTED)
        self.clock.advance(seconds=3)
        self.assertIsNone(await self.scan(code, engine.SOURCE_CAMERA))
        self.assertEqual(len(self.door.calls), 1)
        self.clock.advance(seconds=engine.CAMERA_COOLDOWN_S)
        self.assertEqual((await self.scan(code, engine.SOURCE_CAMERA)).result, engine.RESULT_GRANTED)
        self.assertEqual(len(self.door.calls), 2)

    async def test_simulation_bypasses_cooldown(self):
        _, code = self.token(max_uses=5)
        await self.scan(code, engine.SOURCE_CAMERA)
        self.assertEqual((await self.scan(code, engine.SOURCE_SIMULATE)).result, engine.RESULT_GRANTED)

    async def test_different_codes_do_not_block_each_other(self):
        _, a = self.token(name="A")
        _, b = self.token(name="B")
        self.assertEqual((await self.scan(a, engine.SOURCE_CAMERA)).result, engine.RESULT_GRANTED)
        self.assertEqual((await self.scan(b, engine.SOURCE_CAMERA)).result, engine.RESULT_GRANTED)


class TestLogsStatsPersistence(Base):
    async def test_logs_newest_first_and_capped(self):
        for i in range(engine.MAX_LOG_ENTRIES + 25):
            await self.scan(f"garbage-{i}")
        logs = self.eng._data["logs"]
        self.assertEqual(len(logs), engine.MAX_LOG_ENTRIES)
        self.assertTrue(logs[0]["code"].startswith("garbage-52"))  # ultimo inserito
        self.assertLessEqual(len(self.eng.get_state()["logs"]), 100)

    async def test_stats(self):
        _, ok = self.token(max_uses=1)
        await self.scan(ok)
        await self.scan(ok)  # esaurito
        await self.scan("boh")
        stats = self.eng.stats()
        self.assertEqual((stats["granted"], stats["denied"]), (1, 2))
        self.assertEqual(stats["active"], 0)

    async def test_events_and_change_callbacks(self):
        _, code = self.token()
        before = self.changes
        await self.scan(code)
        self.assertGreater(self.changes, before)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn("token", self.events[0])
        self.assertNotIn(code, json.dumps(self.events))

    async def test_roundtrip_through_json(self):
        public, code = self.token(name="Idraulico", max_uses=3, valid_until=T0 + timedelta(days=2))
        await self.scan(code)
        stored = json.loads(json.dumps(self.saved[-1]))  # come farebbe lo Store
        reloaded = self.make_engine(stored)
        reloaded.set_test_mode(False)
        state = reloaded.get_state()
        self.assertEqual(state["tokens"][0]["name"], "Idraulico")
        self.assertEqual(state["tokens"][0]["uses_left"], 2)
        self.assertEqual((await reloaded.handle_scan(code, engine.SOURCE_SIMULATE)).result, engine.RESULT_GRANTED)

    def test_snapshot_is_a_deep_copy(self):
        self.token()
        snap = self.eng.snapshot()
        snap["tokens"].clear()
        self.assertEqual(len(self.eng.get_state()["tokens"]), 1)

    def test_clear_logs(self):
        self.eng._data["logs"].append({"x": 1})
        self.eng.clear_logs()
        self.assertEqual(self.eng.get_state()["logs"], [])

    def test_sorting_active_first_then_newest(self):
        old, _ = self.token(name="vecchio")
        self.clock.advance(minutes=1)
        new, _ = self.token(name="nuovo")
        revoked, _ = self.token(name="revocato")
        self.eng.revoke_token(revoked["id"])
        names = [t["name"] for t in self.eng.get_state()["tokens"]]
        self.assertEqual(names, ["nuovo", "vecchio", "revocato"])


class TestDoors(Base):
    def setUp(self) -> None:
        super().setUp()
        self.garage = self.eng.add_door("Garage", "switch.garage", 5)

    async def test_one_scan_opens_all_doors_and_costs_one_access(self):
        public, code = self.token(max_uses=2)
        result = await self.scan(code)
        self.assertEqual(result.result, engine.RESULT_GRANTED)
        self.assertEqual(sorted(result.doors), ["Cancello", "Garage"])
        self.assertEqual(
            sorted(self.door.calls),
            sorted([(self.gate["id"], 3), (self.garage["id"], 5)]),
        )
        state = {t["id"]: t for t in self.eng.get_state()["tokens"]}[public["id"]]
        self.assertEqual((state["uses_left"], state["uses_count"]), (1, 1))

    async def test_token_limited_to_one_door(self):
        _, code = self.token(doors=[self.garage["id"]])
        result = await self.scan(code)
        self.assertEqual(result.doors, ["Garage"])
        self.assertEqual(self.door.calls, [(self.garage["id"], 5)])

    def test_selecting_all_doors_means_all(self):
        public, _ = self.token(doors=[self.gate["id"], self.garage["id"]])
        self.assertIsNone(public["doors"])

    def test_all_doors_token_follows_new_doors(self):
        public, code = self.token()
        third = self.eng.add_door("Pedonale", "switch.pedonale", 2)
        self.assertEqual(len(self.eng._authorized_doors(self.eng._data["tokens"][public["id"]])), 3)
        self.assertIsNotNone(third["id"])

    def test_invalid_door_selection(self):
        for bad in ([], ["nope"], "x", [1]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.token(doors=bad)

    async def test_update_token_doors(self):
        public, code = self.token()
        updated = self.eng.update_token(public["id"], doors=[self.gate["id"]])
        self.assertEqual(updated["doors"], [self.gate["id"]])
        self.assertEqual((await self.scan(code)).doors, ["Cancello"])
        self.assertIsNone(self.eng.update_token(public["id"], doors=None)["doors"])
        # non indicato = invariato
        self.eng.update_token(public["id"], doors=[self.garage["id"]])
        self.assertEqual(self.eng.update_token(public["id"], uses_left=3)["doors"], [self.garage["id"]])

    async def test_partial_failure_still_grants(self):
        _, code = self.token(max_uses=2)
        self.door.fail_ids = {self.garage["id"]}
        result = await self.scan(code)
        self.assertEqual(result.result, engine.RESULT_GRANTED)
        self.assertEqual(result.doors, ["Cancello"])
        entry = self.eng.get_state()["logs"][0]
        self.assertEqual(entry["doors_failed"], ["Garage"])
        self.assertEqual(self.eng.get_state()["tokens"][0]["uses_left"], 1)

    async def test_total_failure_refunds(self):
        public, code = self.token(max_uses=2)
        self.door.fail = True
        result = await self.scan(code)
        self.assertEqual(result.result, engine.RESULT_ERROR)
        self.assertEqual(self.eng.get_state()["tokens"][0]["uses_left"], 2)

    async def test_test_mode_lists_doors_without_opening(self):
        _, code = self.token()
        self.eng.set_test_mode(True)
        result = await self.scan(code)
        self.assertEqual(sorted(result.doors), ["Cancello", "Garage"])
        self.assertFalse(result.door_opened)
        self.assertEqual(self.door.calls, [])

    async def test_deleting_door_updates_tokens(self):
        public, code = self.token(doors=[self.garage["id"]])
        self.eng.delete_door(self.garage["id"])
        self.assertEqual((await self.scan(code)).result, engine.RESULT_NO_DOOR)
        self.assertEqual(self.door.calls, [])

    def test_cannot_delete_last_door(self):
        self.eng.delete_door(self.garage["id"])
        with self.assertRaises(ValueError):
            self.eng.delete_door(self.gate["id"])
        with self.assertRaises(ValueError):
            self.eng.delete_door("nope")

    def test_door_validation(self):
        bad = [
            ("", "switch.x", 3), ("x" * 41, "switch.x", 3), ("A", "sensor.x", 3),
            ("A", "nodomain", 3), ("A", "switch.x", 0), ("A", "switch.x", 31),
            ("A", "switch.x", True), ("A", "switch.x", 2.5), (None, "switch.x", 3),
        ]
        for name, entity, secs in bad:
            with self.subTest(name=name, entity=entity, secs=secs):
                with self.assertRaises(ValueError):
                    self.eng.add_door(name, entity, secs)

    def test_update_door(self):
        updated = self.eng.update_door(self.gate["id"], "Cancello grande", "light.c", 4)
        self.assertEqual((updated["name"], updated["door_entity"], updated["open_seconds"]), ("Cancello grande", "light.c", 4))
        self.assertEqual(self.eng.door_entity(self.gate["id"]), "light.c")
        with self.assertRaises(ValueError):
            self.eng.update_door("nope", "A", "switch.x", 3)


class TestSettings(Base):
    def test_reader(self):
        self.eng.set_reader("image_processing.qr", "camera.porta")
        self.assertEqual(self.eng.reader_entity, "image_processing.qr")
        self.assertEqual(self.reader_changes, 1)
        self.eng.set_reader("image_processing.qr", None)  # stesso lettore: nessun ricarico
        self.assertEqual(self.reader_changes, 1)
        self.assertIsNone(self.eng.camera_entity)
        self.eng.set_reader("image_processing.altro", None)
        self.assertEqual(self.reader_changes, 2)
        for reader, cam in (("sensor.x", None), ("image_processing.qr", "sensor.c"), ("qr", None)):
            with self.subTest(reader=reader, cam=cam):
                with self.assertRaises(ValueError):
                    self.eng.set_reader(reader, cam)
        self.assertEqual(self.eng.get_state()["reader"]["reader_entity"], "image_processing.altro")

    def test_notify_defaults_and_set(self):
        self.assertEqual(self.eng.notify_settings(), {"services": [], "on_granted": True, "on_denied": False})
        out = self.eng.set_notify(["notify.mobile_app_a", "notify.mobile_app_a", "notify.mobile_app_b"], True, True)
        self.assertEqual(out["services"], ["notify.mobile_app_a", "notify.mobile_app_b"])
        self.assertTrue(out["on_denied"])
        self.assertEqual(self.eng.get_state()["settings"]["notify"], out)

    def test_notify_validation(self):
        for bad in (["light.x"], ["notify"], [5], "notify.a", ["notify.a"] * 0 + ["notify.x"] * 21 and [f"notify.s{i}" for i in range(21)]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.eng.set_notify(bad, True, False)

    def test_settings_survive_json_roundtrip(self):
        self.eng.set_reader("image_processing.qr", "camera.p")
        self.eng.set_notify(["notify.mobile_app_a"], False, True)
        reloaded = self.make_engine(json.loads(json.dumps(self.saved[-1])))
        self.assertEqual(reloaded.reader_entity, "image_processing.qr")
        self.assertEqual(reloaded.notify_settings()["services"], ["notify.mobile_app_a"])
        self.assertEqual(len(reloaded.doors), 1)


class TestSearchLogs(Base):
    async def test_search(self):
        _, mario = self.token(name="Mario Rossi")
        _, tecnico = self.token(name="Tecnico caldaia")
        await self.scan(mario)
        await self.scan(tecnico)
        await self.scan("QG-sconosciuto-xyz")
        names = lambda q: [e["name"] for e in self.eng.search_logs(q)]
        self.assertEqual(names("mario"), ["Mario Rossi"])
        self.assertEqual(names("  CALDAIA "), ["Tecnico caldaia"])
        self.assertEqual(len(self.eng.search_logs("")), 3)
        self.assertEqual(len(self.eng.search_logs(None)), 3)
        self.assertEqual(len(self.eng.search_logs("cancello")), 2)  # anche per nome porta
        self.assertEqual(len(self.eng.search_logs("sconosc")), 1)  # anteprima codice sconosciuto
        self.assertEqual(self.eng.search_logs("zzz"), [])
        self.assertEqual(len(self.eng.search_logs("", limit=2)), 2)

    async def test_search_reaches_beyond_the_100_shown(self):
        _, code = self.token(name="Vecchio")
        await self.scan(code)
        for i in range(150):
            await self.scan(f"garbage-{i}")
        self.assertNotIn("Vecchio", [e["name"] for e in self.eng.get_state()["logs"]])
        self.assertEqual(len(self.eng.search_logs("vecchio")), 1)


class TestTimezoneSafety(Base):
    def test_naive_stored_datetimes_are_treated_as_utc(self):
        record = {
            "revoked": False,
            "valid_from": "2026-11-14T11:00:00",
            "valid_until": "2026-11-14T13:00:00",
            "uses_left": None,
        }
        self.assertEqual(self.eng.status_of(record, T0), engine.STATUS_ACTIVE)

    def test_offsets_are_normalised(self):
        # 14:00+02:00 == 12:00 UTC
        public = self.eng.create_token(
            "x",
            valid_from=None,
            valid_until=datetime(2026, 11, 14, 14, 0, tzinfo=timezone(timedelta(hours=2))) + timedelta(hours=3),
            max_uses=None,
        )
        self.assertTrue(public["valid_until"].endswith("+00:00"))
        self.assertEqual(public["valid_until"], "2026-11-14T15:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
