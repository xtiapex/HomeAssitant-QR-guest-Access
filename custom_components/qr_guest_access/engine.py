"""Motore di validazione degli accessi.

Questo modulo NON dipende da Home Assistant: contiene tutte le regole
(token, finestre di validità, accessi residui, porte, log) ed è testabile da
solo. La parte che parla con Home Assistant (relè, lettore, storage) gli
viene iniettata dall'esterno.

Modello: un solo lettore QR e una o più porte (relè). Ogni token apre tutte
le porte oppure solo quelle scelte; un passaggio del QR apre insieme tutte le
porte autorizzate e consuma UN accesso.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

_LOGGER = logging.getLogger(__name__)

TOKEN_PREFIX = "QG-"
MAX_NAME_LEN = 60
MAX_DOOR_NAME_LEN = 40
MAX_USES_LIMIT = 999
MAX_OPEN_SECONDS = 30
MAX_LOG_ENTRIES = 500
CODE_PREVIEW_LEN = 12
MAX_CODE_LEN = 256
CAMERA_COOLDOWN_S = 10.0
MAX_NOTIFY_SERVICES = 20

DOOR_DOMAINS = ("switch", "light", "input_boolean")

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
RESULT_NO_DOOR = "denied_no_door"
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

# "non specificato" (None ha già un significato: nessuna data di fine / illimitati)
_UNSET: Any = object()


class DoorDriver(Protocol):
    """Qualcosa che sa aprire una porta."""

    async def open(self, door_id: str, seconds: float) -> None:  # pragma: no cover - protocollo
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
    doors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "name": self.name,
            "door_opened": self.door_opened,
            "test": self.test,
            "source": self.source,
            "token_id": self.token_id,
            "doors": list(self.doors),
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


def _domain(entity_id: Any) -> str | None:
    if isinstance(entity_id, str) and "." in entity_id:
        return entity_id.split(".", 1)[0]
    return None


class AccessEngine:
    """Gestisce token, porte, validazione, consumo degli accessi e log."""

    def __init__(
        self,
        data: dict[str, Any] | None,
        door: DoorDriver,
        clock: Callable[[], datetime],
        persist: Callable[[Callable[[], dict[str, Any]]], None] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_reader_changed: Callable[[], None] | None = None,
    ) -> None:
        self._data: dict[str, Any] = data if data else {}
        self._door = door
        self._clock = clock
        self._persist = persist
        self._on_event = on_event
        self._on_change = on_change
        self._on_reader_changed = on_reader_changed

        self._data.setdefault("version", 2)
        settings = self._data.setdefault("settings", {})
        # Alla prima installazione la modalità test è attiva: la porta non si
        # apre finché non la disattivi tu dal pannello.
        settings.setdefault("test_mode", True)
        settings.setdefault("reader_entity", None)
        settings.setdefault("camera_entity", None)
        notify = settings.setdefault("notify", {})
        notify.setdefault("services", [])
        notify.setdefault("on_granted", True)
        notify.setdefault("on_denied", False)
        self._data.setdefault("doors", {})
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
    # Impostazioni generali
    # ------------------------------------------------------------------

    @property
    def test_mode(self) -> bool:
        return bool(self._data["settings"]["test_mode"])

    def set_test_mode(self, enabled: bool) -> None:
        self._data["settings"]["test_mode"] = bool(enabled)
        self._changed()

    @property
    def reader_entity(self) -> str | None:
        return self._data["settings"]["reader_entity"]

    @property
    def camera_entity(self) -> str | None:
        return self._data["settings"]["camera_entity"]

    def set_reader(self, reader_entity: str, camera_entity: str | None) -> None:
        """Imposta il lettore QR (image_processing) e la telecamera per l'anteprima."""
        if _domain(reader_entity) != "image_processing":
            raise ValueError("Il lettore QR deve essere un'entità image_processing.")
        camera_entity = camera_entity or None
        if camera_entity is not None and _domain(camera_entity) != "camera":
            raise ValueError("La telecamera deve essere un'entità camera.")
        changed = reader_entity != self.reader_entity
        self._data["settings"]["reader_entity"] = reader_entity
        self._data["settings"]["camera_entity"] = camera_entity
        self._changed()
        if changed and self._on_reader_changed is not None:
            self._on_reader_changed()

    def notify_settings(self) -> dict[str, Any]:
        return copy.deepcopy(self._data["settings"]["notify"])

    def set_notify(self, services: list[str], on_granted: bool, on_denied: bool) -> dict[str, Any]:
        """Servizi notify (es. notify.mobile_app_telefono) a cui avvisare delle aperture."""
        if not isinstance(services, list) or len(services) > MAX_NOTIFY_SERVICES:
            raise ValueError("Elenco dei dispositivi non valido.")
        clean: list[str] = []
        for service in services:
            if not isinstance(service, str) or _domain(service) != "notify" or len(service) > 100:
                raise ValueError(f"Servizio di notifica non valido: {service!r}")
            if service not in clean:
                clean.append(service)
        self._data["settings"]["notify"] = {
            "services": clean,
            "on_granted": bool(on_granted),
            "on_denied": bool(on_denied),
        }
        self._changed()
        return self.notify_settings()

    # ------------------------------------------------------------------
    # Porte
    # ------------------------------------------------------------------

    @property
    def doors(self) -> list[dict[str, Any]]:
        return [dict(d) for d in self._data["doors"].values()]

    def door_entity(self, door_id: str) -> str | None:
        door = self._data["doors"].get(door_id)
        return door["door_entity"] if door else None

    def _clean_door(self, name: Any, door_entity: Any, open_seconds: Any) -> tuple[str, str, int]:
        name = (name or "").strip() if isinstance(name, str) else ""
        if not name:
            raise ValueError("Il nome della porta è obbligatorio.")
        if len(name) > MAX_DOOR_NAME_LEN:
            raise ValueError(f"Il nome della porta può avere al massimo {MAX_DOOR_NAME_LEN} caratteri.")
        if _domain(door_entity) not in DOOR_DOMAINS:
            raise ValueError("Il relè deve essere un interruttore (switch, light o input_boolean).")
        if isinstance(open_seconds, bool) or not isinstance(open_seconds, int):
            raise ValueError("I secondi di apertura devono essere un numero intero.")
        if not 1 <= open_seconds <= MAX_OPEN_SECONDS:
            raise ValueError(f"I secondi di apertura devono essere tra 1 e {MAX_OPEN_SECONDS}.")
        return name, door_entity, open_seconds

    def add_door(self, name: str, door_entity: str, open_seconds: int) -> dict[str, Any]:
        name, door_entity, open_seconds = self._clean_door(name, door_entity, open_seconds)
        door_id = secrets.token_hex(3)
        while door_id in self._data["doors"]:
            door_id = secrets.token_hex(3)
        record = {
            "id": door_id,
            "name": name,
            "door_entity": door_entity,
            "open_seconds": open_seconds,
        }
        self._data["doors"][door_id] = record
        self._changed()
        return dict(record)

    def update_door(self, door_id: str, name: str, door_entity: str, open_seconds: int) -> dict[str, Any]:
        record = self._data["doors"].get(door_id)
        if record is None:
            raise ValueError("Porta non trovata.")
        name, door_entity, open_seconds = self._clean_door(name, door_entity, open_seconds)
        record.update(name=name, door_entity=door_entity, open_seconds=open_seconds)
        self._changed()
        return dict(record)

    def delete_door(self, door_id: str) -> None:
        if door_id not in self._data["doors"]:
            raise ValueError("Porta non trovata.")
        if len(self._data["doors"]) == 1:
            raise ValueError("Deve restare almeno una porta.")
        del self._data["doors"][door_id]
        # I QR che aprivano solo quella porta non la aprono più (e se era l'unica, non aprono nulla).
        for token in self._data["tokens"].values():
            if token.get("doors") is not None and door_id in token["doors"]:
                token["doors"] = [d for d in token["doors"] if d != door_id]
        self._changed()

    def _validate_doors(self, doors: Any) -> list[str] | None:
        """None = tutte le porte (anche quelle aggiunte in futuro)."""
        if doors is None:
            return None
        if not isinstance(doors, list) or not all(isinstance(d, str) for d in doors):
            raise ValueError("Elenco delle porte non valido.")
        clean: list[str] = []
        for door_id in doors:
            if door_id not in self._data["doors"]:
                raise ValueError("Porta non trovata.")
            if door_id not in clean:
                clean.append(door_id)
        if not clean:
            raise ValueError("Scegli almeno una porta.")
        if set(clean) == set(self._data["doors"]):
            return None
        return clean

    def _authorized_doors(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        allowed = record.get("doors")
        doors = self._data["doors"]
        if allowed is None:
            return list(doors.values())
        return [doors[d] for d in allowed if d in doors]

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------

    def create_token(
        self,
        name: str,
        valid_from: datetime | None,
        valid_until: datetime | None,
        max_uses: int | None,
        doors: list[str] | None = None,
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

        door_list = self._validate_doors(doors)

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
            "doors": door_list,
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

    def update_token(
        self,
        token_id: str,
        valid_from: datetime | None = _UNSET,
        valid_until: datetime | None = _UNSET,
        uses_left: int | None = _UNSET,
        doors: list[str] | None = _UNSET,
    ) -> dict[str, Any]:
        """Modifica date, accessi e porte di un token (il nome e il codice restano fissi).

        - valid_from: None o non indicato = lascia l'inizio com'è.
        - valid_until: non indicato = lascia com'è; None = nessuna data di fine.
        - uses_left: non indicato = lascia com'è; None = accessi illimitati;
          un numero = quanti accessi restano DA ORA (gli usi già fatti restano nel conteggio).
        - doors: non indicato = lascia com'è; None = tutte le porte; una lista = solo quelle.
        Un token scaduto o esaurito torna attivo se la modifica lo permette.
        Solleva ValueError (messaggio in italiano) se la modifica non è valida.
        """
        record = self._data["tokens"].get(token_id)
        if record is None:
            raise ValueError("Token non trovato.")
        now = self._clock()

        new_from = _parse(record["valid_from"])
        if valid_from is not _UNSET and valid_from is not None:
            new_from = valid_from

        if valid_until is _UNSET:
            new_until = _parse(record["valid_until"]) if record["valid_until"] else None
        else:
            new_until = valid_until
            # una data di fine già passata si rifiuta solo se la stai cambiando adesso
            if (
                new_until is not None
                and new_until <= now
                and _iso(new_until) != record["valid_until"]
            ):
                raise ValueError("La data di fine è già passata.")
        if new_until is not None and new_until <= new_from:
            raise ValueError("La data di fine deve essere successiva a quella di inizio.")

        if uses_left is _UNSET:
            new_max, new_left = record["max_uses"], record["uses_left"]
        elif uses_left is None:
            new_max = new_left = None
        else:
            if isinstance(uses_left, bool) or not isinstance(uses_left, int):
                raise ValueError("Il numero di accessi deve essere un intero.")
            if not 1 <= uses_left <= MAX_USES_LIMIT:
                raise ValueError(f"Il numero di accessi deve essere tra 1 e {MAX_USES_LIMIT}.")
            new_left = uses_left
            new_max = record["uses_count"] + uses_left

        if new_left is None and new_until is None:
            raise ValueError("Con accessi illimitati serve una data di fine validità.")

        new_doors = record.get("doors") if doors is _UNSET else self._validate_doors(doors)

        record["valid_from"] = _iso(new_from)
        record["valid_until"] = _iso(new_until) if new_until else None
        record["max_uses"] = new_max
        record["uses_left"] = new_left
        record["doors"] = new_doors
        self._changed()
        return self._public(record, now)

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
        doors = record.get("doors")
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
            "doors": None if doors is None else list(doors),
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
            return self._finish(RESULT_UNKNOWN, None, code, now, source, [], False, test)

        record = self._data["tokens"][token_id]
        status = self.status_of(record, now)
        if status != STATUS_ACTIVE:
            return self._finish(_DENIED_BY_STATUS[status], record, code, now, source, [], False, test)

        targets = self._authorized_doors(record)
        if not targets:
            return self._finish(RESULT_NO_DOOR, record, code, now, source, [], False, test)
        names = [d["name"] for d in targets]

        if test:
            # Prova a secco: validazione completa, ma niente porte e niente consumo.
            return self._finish(RESULT_GRANTED, record, code, now, source, names, False, True)

        # Il consumo avviene PRIMA di aprire le porte e senza await in mezzo:
        # due scansioni ravvicinate non possono superare il limite di accessi.
        previous_last_used = record["last_used"]
        if record["uses_left"] is not None:
            record["uses_left"] -= 1
        record["uses_count"] += 1
        record["last_used"] = _iso(now)

        outcomes = await asyncio.gather(*(self._open_one(d) for d in targets))
        opened = [d["name"] for d, ok in zip(targets, outcomes) if ok]
        failed = [d["name"] for d, ok in zip(targets, outcomes) if not ok]

        if not opened:  # nessuna porta si è aperta: l'accesso viene restituito
            if record["uses_left"] is not None:
                record["uses_left"] += 1
            record["uses_count"] -= 1
            record["last_used"] = previous_last_used
            return self._finish(RESULT_ERROR, record, code, now, source, [], False, False, failed)

        return self._finish(RESULT_GRANTED, record, code, now, source, opened, True, False, failed)

    async def _open_one(self, door: dict[str, Any]) -> bool:
        try:
            await self._door.open(door["id"], door["open_seconds"])
        except Exception:  # noqa: BLE001 - qualunque errore della porta
            _LOGGER.exception("Apertura fallita per la porta '%s'", door["name"])
            return False
        return True

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
        door_names: list[str],
        door_opened: bool,
        test: bool,
        failed: list[str] | None = None,
    ) -> ScanResult:
        entry = {
            "ts": _iso(now),
            "token_id": record["id"] if record else None,
            "name": record["name"] if record else None,
            "code": None if record else _code_preview(code),
            "result": result,
            "door_opened": door_opened,
            "doors": list(door_names),
            "doors_failed": list(failed or []),
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
            doors=list(door_names),
        )

    # ------------------------------------------------------------------
    # Lettura dati per UI e sensori
    # ------------------------------------------------------------------

    def clear_logs(self) -> None:
        self._data["logs"] = []
        self._changed()

    def search_logs(self, query: str | None, limit: int = 200) -> list[dict[str, Any]]:
        """Cerca nello storico (fino a 500 voci) per nome, porta o codice."""
        needle = (query or "").strip().casefold()
        found: list[dict[str, Any]] = []
        for entry in self._data["logs"]:
            if needle:
                haystack = " ".join(
                    [str(entry.get("name") or ""), str(entry.get("code") or "")]
                    + [str(d) for d in entry.get("doors", [])]
                ).casefold()
                if needle not in haystack:
                    continue
            found.append(dict(entry))
            if len(found) >= limit:
                break
        return found

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
            "doors": self.doors,
            "reader": {
                "reader_entity": self.reader_entity,
                "camera_entity": self.camera_entity,
            },
            "settings": {
                "test_mode": self.test_mode,
                "notify": self.notify_settings(),
            },
            "stats": self.stats(),
            "now": _iso(now),
        }
