"""OwnTracks HTTP location ingest into the telemetry table."""

from __future__ import annotations

import base64
import hmac
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from models import TelemetryPoint


def token_configured() -> bool:
    return bool(os.getenv("OWNTRACKS_TOKEN", "").strip())


def authorized(header: str) -> bool:
    """Accept Bearer or HTTP Basic (password is OWNTRACKS_TOKEN)."""
    expected = os.getenv("OWNTRACKS_TOKEN", "").strip()
    if not expected or not header:
        return False
    scheme, _, rest = header.partition(" ")
    scheme = scheme.lower()
    presented = ""
    if scheme == "bearer":
        presented = rest.strip()
    elif scheme == "basic":
        try:
            decoded = base64.b64decode(rest.strip(), validate=True).decode("utf-8")
        except Exception:
            return False
        if ":" not in decoded:
            return False
        presented = decoded.split(":", 1)[1]
    else:
        return False
    try:
        return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


def to_point(body: dict[str, Any], device_header: str | None) -> TelemetryPoint | None:
    """Map an OwnTracks JSON object onto a telemetry point.

    Waypoints, encrypted blobs, and payloads without coordinates are ignored.
    The device tracker id (`tid`) is the callsign.
    """
    kind = str(body.get("_type") or "location")
    if kind in {"waypoint", "waypoints", "encrypted", "lwt", "cmd", "card"}:
        return None
    if "lat" not in body or "lon" not in body:
        return None
    tid = str(body.get("tid") or "").strip()[:32]
    callsign = tid or "OT"
    device = _device_id(device_header, callsign)
    charging = _charging(body.get("bs"))
    raw = {
        "ts": _timestamp(body.get("tst")),
        "deviceId": device,
        "callsign": callsign,
        "lat": body.get("lat"),
        "lon": body.get("lon"),
        "alt": _optional(body.get("alt"), -500, 100000),
        "accuracy": _optional(body.get("acc"), 0, 1000000),
        "heading": _optional(body.get("cog"), 0, 360),
        "speed": _optional(body.get("vel"), 0, 2000),
        "battery": _optional(body.get("batt"), -1, 100),
        "charging": charging,
        "source": "owntracks",
    }
    try:
        return TelemetryPoint.model_validate(raw)
    except ValidationError:
        raise


def _device_id(device_header: str | None, callsign: str) -> str:
    raw = (device_header or "").strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_.")[:64]
    if cleaned:
        return cleaned
    return f"owntracks-{callsign}"[:64]


def _timestamp(tst: Any) -> str:
    try:
        value = float(tst)
    except (TypeError, ValueError):
        value = datetime.now(timezone.utc).timestamp()
    if value > 10**12:
        value = value / 1000.0
    if value < 0:
        value = datetime.now(timezone.utc).timestamp()
    moment = datetime.fromtimestamp(value, timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _optional(value: Any, low: float, high: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < low or number > high:
        return None
    return number


def _charging(bs: Any) -> bool | None:
    # OwnTracks bs: 0 unknown, 1 unplugged, 2 charging, 3 full.
    try:
        code = int(bs)
    except (TypeError, ValueError):
        return None
    if code == 1:
        return False
    if code in {2, 3}:
        return True
    return None
