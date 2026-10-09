"""OwnTracks / Traccar-compatible telemetry ingest helpers."""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("TraccarReceiver")


def _load_key() -> Optional[bytes]:
    raw = os.getenv("TELEMETRY_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw)
        if len(key) != 32:
            logger.error("TELEMETRY_ENCRYPTION_KEY must decode to 32 bytes")
            return None
        return key
    except Exception as e:
        logger.error("Invalid TELEMETRY_ENCRYPTION_KEY: %s", e)
        return None


def decrypt_envelope(envelope: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Decrypt sovereign-aes-gcm-v1 envelope when a shared key is configured."""
    key = _load_key()
    if key is None:
        return None
    try:
        iv = base64.b64decode(envelope["iv"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        logger.error("Telemetry decrypt failed: %s", e)
        return None


async def persist_point(db, point: dict[str, Any], *, encrypted: bool = False, raw_envelope: str | None = None) -> None:
    await db.execute(
        """
        INSERT INTO telemetry (
            ts, device_id, callsign, lat, lon, alt, accuracy,
            heading, speed, battery, charging, source, encrypted, raw_envelope
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            point.get("ts"),
            point.get("deviceId"),
            point.get("callsign"),
            point.get("lat"),
            point.get("lon"),
            point.get("alt"),
            point.get("accuracy"),
            point.get("heading"),
            point.get("speed"),
            point.get("battery"),
            1 if point.get("charging") else 0 if point.get("charging") is not None else None,
            point.get("source"),
            1 if encrypted else 0,
            raw_envelope,
        ),
    )
    await db.commit()
