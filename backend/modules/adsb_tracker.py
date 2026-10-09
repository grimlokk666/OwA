"""ADS-B proximity via local dump1090 / readsb — no FlightRadar24 SaaS."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("ADSB_Module")

DUMP1090_URL = os.getenv("DUMP1090_URL", "http://127.0.0.1:8080/data/aircraft.json")


async def fetch_local_aircraft() -> list[dict[str, Any]]:
    """Pull aircraft JSON from a local dump1090/readsb instance when present."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(DUMP1090_URL)
            if response.status_code == 200:
                data = response.json()
                return data.get("aircraft", data if isinstance(data, list) else [])
    except Exception as e:
        logger.debug("Local ADS-B feed unavailable: %s", e)
    return []
