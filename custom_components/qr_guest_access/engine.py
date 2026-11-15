"""Motore di validazione degli accessi.

Questo modulo NON dipende da Home Assistant: contiene tutte le regole
(token, finestre di validità, accessi residui, log) ed è testabile da solo.
La parte che parla con Home Assistant (porta, lettore, storage) gli viene
iniettata dall'esterno.
"""
from __future__ import annotations

import copy
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

_LOGGER = logging.getLogger(__name__)

TOKEN_PREFIX = "QG-"
MAX_NAME_LEN = 60
MAX_USES_LIMIT = 999
MAX_LOG_ENTRIES = 500
CODE_PREVIEW_LEN = 12
MAX_CODE_LEN = 256
CAMERA_COOLDOWN_S = 10.0

# Stati di un token
STATUS_ACTIVE = "active"
STATUS_PENDING = "pending"
STATUS_EXPIRED = "expired"
STATUS_EXHAUSTED = "exhausted"
STATUS_REVOKED = "revoked"

_STATUS_RANK = {
    STATUS_ACTIVE: 0,
    STATUS_PENDING: 1,
    STATUS_EXHAUSTED: 2,
    STATUS_EXPIRED: 3,
    STATUS_REVOKED: 4,
}

# Esiti di una scansione
RESULT_GRANTED = "granted"
RESULT_UNKNOWN = "denied_unknown"
RESULT_REVOKED = "denied_revoked"
RESULT_EXPIRED = "denied_expired"
RESULT_NOT_STARTED = "denied_not_started"
RESULT_EXHAUSTED = "denied_exhausted"
RESULT_ERROR = "error"

_DENIED_BY_STATUS = {
    STATUS_REVOKED: RESULT_REVOKED,
    STATUS_PENDING: RESULT_NOT_STARTED,
    STATUS_EXPIRED: RESULT_EXPIRED,
    STATUS_EXHAUSTED: RESULT_EXHAUSTED,
}

SOURCE_CAMERA = "camera"
SOURCE_SIMULATE = "simulate"

# Valori che il lettore QR usa per dire "nessun codice visibile"
IGNORED_CODES = {"", "unknown", "unavailable", "none"}


class DoorDriver(Protocol):
    """Qualcosa che sa aprire la porta."""

    async def open(self, seconds: float) -> None:  # pragma: no cover - protocollo
        ...


@dataclass
class ScanResult:
    """Esito di una scansione."""

    result: str
    name: str | None
    door_opened: bool
    test: bool
    source: str
    token_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "name": self.name,
            "door_opened": self.door_opened,
            "test": self.test,
            "source": self.source,
            "token_id": self.token_id,
        }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:  # difesa: i dati salvati sono sempre UTC
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _code_preview(code: str) -> str:
    """Anteprima sicura di un codice sconosciuto (mai il codice intero)."""
    head = "".join(ch if ch.isprintable() else "?" for ch in code[:CODE_PREVIEW_LEN])
    return head + ("…" if len(code) > CODE_PREVIEW_LEN else "")


class AccessEngine:
    """Gestisce token, validazione, consumo degli accessi e log."""

    def __init__(
        self,
        data: dict[str, Any] | None,
        door: DoorDriver,
        clock: Callable[[], datetime],
        open_seconds: float = 3,
        persist: Callable[[Callable[[], dict[str, Any]]], None] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._data: dict[str, Any] = data if data else {}
        self._door = door
        self._clock = clock
        self._open_seconds = open_seconds
        self._persist = persist
        self._on_event = on_event
        self._on_change = on_change

        self._data.setdefault("version", 1)
        settings = self._data.setdefault("settings", {})
        # Alla prima installazione la modalità test è attiva: la porta non si
        # apre finché non la disattivi tu dal pannello.
        settings.setdefault("test_mode", True)
        self._data.setdefault("tokens", {})
        self._data.setdefault("logs", [])
        stats = self._data.setdefault("stats", {})
        stats.setdefault("granted", 0)
        stats.setdefault("denied", 0)

        self._index: dict[str, str] = {}
        self._last_seen: dict[str, datetime] = {}
        self._rebuild_index()

    # ------------------------------------------------------------------
    # Persistenza / notifiche
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Copia profonda dei dati, sicura da serializzare."""
        return copy.deepcopy(self._data)

    def _changed(self) -> None:
        if self._persist is not None:
            self._persist(self.snapshot)
        if self._on_change is not None:
            self._on_change()

    def _rebuild_index(self) -> None:
        self._index = {t["token"]: tid for tid, t in self._data["tokens"].items()}

    # ------------------------------------------------------------------
    # Impostazioni
    # ------------------------------------------------------------------

    @property
    def test_mode(self) -> bool:
        return bool(self._data["settings"]["test_mode"])

    def set_test_mode(self, enabled: bool) -> None:
        self._data["settings"]["test_mode"] = bool(enabled)
        self._changed()

    @property
    def open_seconds(self) -> float:
        return self._open_seconds

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------

    def create_token(
        self,
        name: str,
        valid_from: datetime | None,
        valid_until: datetime | None,
        max_uses: int | None,
    ) -> dict[str, Any]:
        """Crea un token. Solleva ValueError (messaggio in italiano) se non valido."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Il nome è obbligatorio.")
        if len(name) > MAX_NAME_LEN:
            raise ValueError(f"Il nome può avere al massimo {MAX_NAME_LEN} caratteri.")

        now = self._clock()
        start = valid_from or now
        if valid_until is not None:
            if valid_until <= start:
                raise ValueError("La data di fine deve essere successiva a quella di inizio.")
            if valid_until <= now:
                raise ValueError("La data di fine è già passata.")

        if max_uses is None:
            if valid_until is None:
                raise ValueError("Con accessi illimitati serve una data di fine validità.")
        else:
            if isinstance(max_uses, bool) or not isinstance(max_uses, int):
                raise ValueError("Il numero di accessi deve essere un intero.")
            if not 1 <= max_uses <= MAX_USES_LIMIT:
                raise ValueError(f"Il numero di accessi deve essere tra 1 e {MAX_USES_LIMIT}.")

        token = TOKEN_PREFIX + secrets.token_urlsafe(24)
        while token in self._index:  # collisione praticamente impossibile
            token = TOKEN_PREFIX + secrets.token_urlsafe(24)
        token_id = secrets.token_hex(4)
        while token_id in self._data["tokens"]:
            token_id = secrets.token_hex(4)

        record = {
            "id": token_id,
            "token": token,
            "name": name,
            "created_at": _iso(now),
            "valid_from": _iso(start),
            "valid_until": _iso(valid_until) if valid_until else None,
            "max_uses": max_uses,
            "uses_left": max_uses,
            "uses_count": 0,
            "last_used": None,
            "revoked": False,
        }
        self._data["tokens"][token_id] = record
        self._index[token] = token_id
        self._changed()
        return self._public(record, now)

    def token_secret(self, token_id: str) -> str | None:
        record = self._data["tokens"].get(token_id)
        return record["token"] if record else None

    def revoke_token(self, token_id: str) -> bool:
        record = self._data["tokens"].get(token_id)
        if record is None:
            return False
        record["revoked"] = True
        self._changed()
        return True

    def restore_token(self, token_id: str) -> bool:
        """Riabilita un token revocato. False se non esiste o non era revocato.

        Il token torna com'era: stessi accessi residui e stessa finestra di
        validità. Se nel frattempo è scaduto o esaurito, resterà tale.
        """
        record = self._data["tokens"].get(token_id)
        if record is None or not record["revoked"]:
            return False
        record["revoked"] = False
        self._changed()
        return True

    def delete_token(self, token_id: str) -> bool:
        record = self._data["tokens"].pop(token_id, None)
        if record is None:
            return False
        self._index.pop(record["token"], None)
        self._changed()
        return True

    def status_of(self, record: dict[str, Any], now: datetime | None = None) -> str:
        now = now or self._clock()
        if record["revoked"]:
            return STATUS_REVOKED
        if now < _parse(record["valid_from"]):
            return STATUS_PENDING
        if record["valid_until"] and now > _parse(record["valid_until"]):
            return STATUS_EXPIRED
        if record["uses_left"] is not None and record["uses_left"] <= 0:
            return STATUS_EXHAUSTED
        return STATUS_ACTIVE

    def _public(self, record: dict[str, Any], now: datetime) -> dict[str, Any]:
        """Vista di un token senza il segreto."""
        return {
            "id": record["id"],
            "name": record["name"],
            "status": self.status_of(record, now),
            "created_at": record["created_at"],
            "valid_from": record["valid_from"],
            "valid_until": record["valid_until"],
            "max_uses": record["max_uses"],
            "uses_left": record["uses_left"],
            "uses_count": record["uses_count"],
            "last_used": record["last_used"],
            "revoked": record["revoked"],
        }

    # ------------------------------------------------------------------
    # Scansione
    # ------------------------------------------------------------------

    async def handle_scan(self, code: str | None, source: str = SOURCE_CAMERA) -> ScanResult | None:
        """Gestisce un codice letto. Restituisce None se va ignorato."""
        code = (code or "").strip()
        if code.lower() in IGNORED_CODES:
            return None

        now = self._clock()
        if source == SOURCE_CAMERA:
            if self._in_cooldown(code, now):
                return None
            self._last_seen[code[:MAX_CODE_LEN]] = now
            self._prune_last_seen(now)

        test = self.test_mode
        token_id = self._index.get(code) if len(code) <= MAX_CODE_LEN else None
        if token_id is None:
            return self._finish(RESULT_UNKNOWN, None, code, now, source, False, test)

        record = self._data["tokens"][token_id]
        status = self.status_of(record, now)
        if status != STATUS_ACTIVE:
            return self._finish(_DENIED_BY_STATUS[status], record, code, now, source, False, test)

        if test:
            # Prova a secco: validazione completa, ma niente porta e niente consumo.
            return self._finish(RESULT_GRANTED, record, code, now, source, False, True)

        # Il consumo avviene PRIMA di aprire la porta e senza await in mezzo:
        # due scansioni ravvicinate non possono superare il limite di accessi.
        previous_last_used = record["last_used"]
        if record["uses_left"] is not None:
            record["uses_left"] -= 1
        record["uses_count"] += 1
        record["last_used"] = _iso(now)

        try:
            await self._door.open(self._open_seconds)
        except Exception:  # noqa: BLE001 - qualunque errore della porta
            _LOGGER.exception("Apertura porta fallita per il token '%s'", record["name"])
            if record["uses_left"] is not None:
                record["uses_left"] += 1
            record["uses_count"] -= 1
            record["last_used"] = previous_last_used
            return self._finish(RESULT_ERROR, record, code, now, source, False, False)

        return self._finish(RESULT_GRANTED, record, code, now, source, True, False)

    def _in_cooldown(self, code: str, now: datetime) -> bool:
        last = self._last_seen.get(code[:MAX_CODE_LEN])
        return last is not None and (now - last).total_seconds() < CAMERA_COOLDOWN_S

    def _prune_last_seen(self, now: datetime) -> None:
        if len(self._last_seen) < 50:
            return
        self._last_seen = {
            code: seen
            for code, seen in self._last_seen.items()
            if (now - seen).total_seconds() < 60
        }

    def _finish(
        self,
        result: str,
        record: dict[str, Any] | None,
        code: str,
        now: datetime,
        source: str,
        door_opened: bool,
        test: bool,
    ) -> ScanResult:
        entry = {
            "ts": _iso(now),
            "token_id": record["id"] if record else None,
            "name": record["name"] if record else None,
            "code": None if record else _code_preview(code),
            "result": result,
            "door_opened": door_opened,
            "test": test,
            "source": source,
        }
        logs = self._data["logs"]
        logs.insert(0, entry)
        del logs[MAX_LOG_ENTRIES:]

        if not test:
            if result == RESULT_GRANTED:
                self._data["stats"]["granted"] += 1
            elif result.startswith("denied"):
                self._data["stats"]["denied"] += 1

        self._changed()
        if self._on_event is not None:
            self._on_event(dict(entry))
        return ScanResult(
            result=result,
            name=entry["name"],
            door_opened=door_opened,
            test=test,
            source=source,
            token_id=entry["token_id"],
        )

    # ------------------------------------------------------------------
    # Lettura dati per UI e sensori
    # ------------------------------------------------------------------

    def clear_logs(self) -> None:
        self._data["logs"] = []
        self._changed()

    def stats(self) -> dict[str, int]:
        now = self._clock()
        statuses = [self.status_of(t, now) for t in self._data["tokens"].values()]
        return {
            "active": statuses.count(STATUS_ACTIVE),
            "pending": statuses.count(STATUS_PENDING),
            "total": len(statuses),
            "granted": self._data["stats"]["granted"],
            "denied": self._data["stats"]["denied"],
        }

    def last_log(self) -> dict[str, Any] | None:
        logs = self._data["logs"]
        return dict(logs[0]) if logs else None

    def get_state(self) -> dict[str, Any]:
        now = self._clock()
        tokens = [self._public(t, now) for t in self._data["tokens"].values()]
        tokens.sort(key=lambda t: t["created_at"], reverse=True)
        tokens.sort(key=lambda t: _STATUS_RANK[t["status"]])  # stabile
        return {
            "tokens": tokens,
            "logs": [dict(entry) for entry in self._data["logs"][:100]],
            "settings": {
                "test_mode": self.test_mode,
                "open_seconds": self._open_seconds,
            },
            "stats": self.stats(),
            "now": _iso(now),
        }
