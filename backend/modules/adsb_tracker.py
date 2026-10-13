"""ADS-B proximity via local dump1090 / readsb — no FlightRadar24 SaaS."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("ADSB_Module")


def dump1090_url() -> str:
    """Empty means no receiver is configured. There is no implicit localhost default."""
    return os.getenv("DUMP1090_URL", "").strip()


async def aircraft_status() -> dict[str, Any]:
    """Return aircraft plus a configured flag. Never raises for a missing receiver."""
    url = dump1090_url()
    if not url:
        return {
            "aircraft": [],
            "configured": False,
            "status": "no receiver configured",
        }
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=False) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                aircraft = data.get("aircraft", data if isinstance(data, list) else [])
                if not isinstance(aircraft, list):
                    aircraft = []
                return {"aircraft": aircraft, "configured": True, "status": "ok"}
    except Exception as exc:
        logger.debug("Local ADS-B feed unavailable: %s", type(exc).__name__)
    return {"aircraft": [], "configured": True, "status": "offline"}


async def fetch_local_aircraft() -> list[dict[str, Any]]:
    """Pull aircraft JSON from a local dump1090/readsb instance when one is set."""
    status = await aircraft_status()
    return list(status["aircraft"])
