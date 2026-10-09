"""DOT / public traffic camera feed stubs — cache frames locally when available."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("TrafficCams")


async def fetch_nearby_cameras(lat: float, lon: float, radius_km: float = 25.0) -> list[dict[str, Any]]:
    """
    Placeholder for state DOT camera index lookups.
    Prefer local/cached camera metadata over commercial map SDKs.
    """
    logger.info(
        "Traffic cam query lat=%.4f lon=%.4f radius_km=%.1f (stub — wire your DOT source)",
        lat,
        lon,
        radius_km,
    )
    return []
