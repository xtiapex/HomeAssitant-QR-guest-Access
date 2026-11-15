"""Costanti di QR Guest Access."""
from __future__ import annotations

DOMAIN = "qr_guest_access"
VERSION = "1.1.1"

PLATFORMS = ["sensor"]

# Chiavi di configurazione
CONF_READER_ENTITY = "reader_entity"  # image_processing.qr_... (integrazione qrcode)
CONF_DOOR_ENTITY = "door_entity"  # switch della Shelly 1
CONF_CAMERA_ENTITY = "camera_entity"  # opzionale: solo per l'anteprima nel pannello
CONF_OPEN_SECONDS = "open_seconds"

DEFAULT_OPEN_SECONDS = 3

# Storage (chiave nuova: non tocca i dati della vecchia versione)
STORAGE_KEY = f"{DOMAIN}_v2"
STORAGE_VERSION = 1
SAVE_DELAY = 1.0

# Pannello
PANEL_URL_PATH = "qr-guest-access"
PANEL_ELEMENT = "qr-guest-access-panel"
STATIC_URL = "/qr_guest_access_static"

# Eventi e segnali
EVENT_SCAN = f"{DOMAIN}_scan"  # per le automazioni: ogni scansione registrata
EVENT_UPDATE = f"{DOMAIN}_update"  # per il pannello: qualcosa è cambiato
SIGNAL_UPDATE = f"{DOMAIN}_signal_update"  # per i sensori
