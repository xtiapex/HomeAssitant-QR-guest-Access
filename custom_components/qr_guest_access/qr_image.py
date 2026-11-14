"""Generazione dell'immagine QR (PNG)."""
from __future__ import annotations

import io


class QRImageError(Exception):
    """Non è stato possibile generare l'immagine."""


def make_png(data: str, scale: int = 10, border: int = 4) -> bytes:
    """Restituisce un PNG del QR. Sincrono: chiamalo da un executor."""
    try:
        import segno
    except ImportError as err:  # la libreria è nel manifest, ma meglio un errore chiaro
        raise QRImageError("La libreria 'segno' non è installata.") from err

    try:
        # Livello M: meno moduli, quindi quadrati più grandi e più facili da
        # leggere per la telecamera. Lo schermo di un telefono non si rovina.
        qr = segno.make(data, error="m", micro=False)
        buffer = io.BytesIO()
        qr.save(buffer, kind="png", scale=scale, border=border, dark="#000000", light="#ffffff")
    except Exception as err:  # noqa: BLE001
        raise QRImageError(f"Generazione del QR non riuscita: {err}") from err
    return buffer.getvalue()
