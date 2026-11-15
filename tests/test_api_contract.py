"""Controlli di coerenza tra pannello (JS) e comandi WebSocket (Python).

Home Assistant assegna il campo "id" a ogni messaggio WebSocket (è il numero
progressivo della richiesta) e SOVRASCRIVE quello che il pannello ci mette.
Quindi nessun comando può usare "id" per un proprio dato: la versione 1.0.0
lo faceva per mostrare/revocare/eliminare un QR, e i pulsanti non funzionavano.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "qr_guest_access"
API = (PKG / "api.py").read_text(encoding="utf-8")
PANEL = (PKG / "frontend" / "panel.js").read_text(encoding="utf-8")


def _commands() -> list[str]:
    return sorted(set(re.findall(r'"type"\): "(qr_guest_access/[a-z_]+)"', API)))


class ApiContract(unittest.TestCase):
    def test_no_command_schema_uses_the_reserved_id_field(self):
        self.assertNotRegex(API, r'vol\.(Required|Optional)\("id"\)')

    def test_panel_never_sends_an_id_field(self):
        for call in re.findall(r"callWS\(\{(.*?)\}\)", PANEL, flags=re.S):
            self.assertIsNone(re.search(r"(^|[\s,{])id\s*[:,]", call), f"campo 'id' in: {call!r}")
            self.assertNotIn("...(code ? { code } : { id", call)

    def test_every_command_used_by_the_panel_is_registered(self):
        registered = set(_commands())
        used = set(re.findall(r'type: "(qr_guest_access/[a-z_]+)"', PANEL))
        # azioni composte: `qr_guest_access/${action}` con action = revoke | delete
        used |= {"qr_guest_access/revoke", "qr_guest_access/delete"}
        self.assertIn('type: "qr_guest_access/restore", token_id: id', PANEL)
        used.add("qr_guest_access/restore")
        self.assertIn('type: "qr_guest_access/update",\n        token_id: this._editId', PANEL)
        used.add("qr_guest_access/update")
        self.assertTrue(used <= registered, f"non registrati: {used - registered}")

    def test_commands_that_take_a_token_use_token_id_on_both_sides(self):
        for command in ("qr", "revoke", "restore", "delete"):
            self.assertRegex(API, rf'"qr_guest_access/{command}", vol\.Required\("token_id"\)')
        self.assertRegex(API, r'"qr_guest_access/update",\s*vol\.Required\("token_id"\)')
        self.assertIn('type: "qr_guest_access/qr", token_id: id', PANEL)
        self.assertIn("type: `qr_guest_access/${action}`, token_id: id", PANEL)

    def test_png_download_uses_a_signed_admin_only_view(self):
        self.assertIn('url = "/api/qr_guest_access/qr/{token_id}"', API)
        self.assertIn("user.is_admin", API)
        self.assertIn("register_view(QRImageView(hass))", API)
        self.assertIn('type: "auth/sign_path", path: `/api/qr_guest_access/qr/${img.tokenId}`', PANEL)

    def test_all_registered_commands_are_in_the_register_list(self):
        listed = set(re.findall(r"^\s+(ws_[a-z_]+),$", API, flags=re.M))
        defined = set(re.findall(r"^(?:async )?def (ws_[a-z_]+)\(", API, flags=re.M))
        self.assertEqual(listed, defined)


if __name__ == "__main__":
    unittest.main()
