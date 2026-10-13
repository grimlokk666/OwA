"""Proxy geocoding and routing to optional local Nominatim and Valhalla."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from modules.polyline import decode_polyline

logger = logging.getLogger("NavProxy")

PROFILES = {"auto", "bicycle", "pedestrian"}


class NavError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def nominatim_url() -> str:
    return os.getenv("NOMINATIM_URL", "").strip().rstrip("/")


def valhalla_url() -> str:
    return os.getenv("VALHALLA_URL", "").strip().rstrip("/")


async def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    base = nominatim_url()
    if not base:
        raise NavError(503, "geocoder not configured")
    limit = max(1, min(int(limit), 10))
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(limit),
        "addressdetails": "0",
        "countrycodes": "us",
        # Ohio and the neighboring states. Unbounded so a miss can still return.
        "viewbox": "-90.5,48.4,-74.6,36.4",
        "bounded": "0",
    }
    headers = {"User-Agent": "SovereignOverwatch/1.0 (local nominatim proxy)", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(f"{base}/search", params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.info("Nominatim unreachable: %s", type(exc).__name__)
        raise NavError(503, "geocoder unavailable") from exc
    if response.status_code >= 500:
        raise NavError(503, "geocoder unavailable")
    if response.status_code >= 400:
        raise NavError(502, "geocoder rejected the query")
    try:
        payload = response.json()
    except ValueError as exc:
        raise NavError(502, "geocoder returned an unreadable response") from exc
    if not isinstance(payload, list):
        raise NavError(502, "geocoder returned an unreadable response")
    results: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(row.get("display_name") or row.get("name") or query)[:300]
        results.append({"label": label, "lat": lat, "lon": lon})
    return results


async def route(origin: dict[str, float], destination: dict[str, float], profile: str) -> dict[str, Any]:
    base = valhalla_url()
    if not base:
        raise NavError(503, "routing not configured")
    if profile not in PROFILES:
        raise NavError(422, "unsupported profile")
    body = {
        "locations": [
            {"lat": origin["lat"], "lon": origin["lon"], "type": "break"},
            {"lat": destination["lat"], "lon": destination["lon"], "type": "break"},
        ],
        "costing": profile,
        "directions_options": {"units": "kilometers", "language": "en-US"},
        "shape_format": "polyline6",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(f"{base}/route", json=body)
    except httpx.HTTPError as exc:
        logger.info("Valhalla unreachable: %s", type(exc).__name__)
        raise NavError(503, "routing unavailable") from exc
    if response.status_code == 400:
        raise NavError(422, _valhalla_error(response) or "no route")
    if response.status_code >= 500:
        raise NavError(503, "routing unavailable")
    if response.status_code >= 400:
        raise NavError(502, _valhalla_error(response) or "routing rejected the request")
    try:
        payload = response.json()
    except ValueError as exc:
        raise NavError(502, "routing returned an unreadable response") from exc
    return _normalize_trip(payload, profile)


def _valhalla_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        message = payload.get("error") or payload.get("message") or ""
        return str(message)[:200]
    return ""


def _normalize_trip(payload: dict[str, Any], profile: str) -> dict[str, Any]:
    trip = payload.get("trip") if isinstance(payload, dict) else None
    if not isinstance(trip, dict):
        raise NavError(502, "routing returned an unreadable response")
    summary = trip.get("summary") if isinstance(trip.get("summary"), dict) else {}
    coordinates: list[list[float]] = []
    steps: list[dict[str, Any]] = []
    legs = trip.get("legs") if isinstance(trip.get("legs"), list) else []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        shape = leg.get("shape")
        if isinstance(shape, str):
            decoded = decode_polyline(shape, 6)
        elif isinstance(shape, dict) and shape.get("type") == "LineString":
            decoded = []
            for pair in shape.get("coordinates") or []:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    decoded.append((float(pair[1]), float(pair[0])))
        else:
            decoded = []
        offset = len(coordinates)
        coordinates.extend([[lat, lon] for lat, lon in decoded])
        maneuvers = leg.get("maneuvers") if isinstance(leg.get("maneuvers"), list) else []
        for maneuver in maneuvers:
            if not isinstance(maneuver, dict):
                continue
            text = (
                maneuver.get("verbal_pre_transition_instruction")
                or maneuver.get("instruction")
                or "Continue"
            )
            begin = maneuver.get("begin_shape_index") or 0
            try:
                begin_index = offset + int(begin)
            except (TypeError, ValueError):
                begin_index = offset
            steps.append(
                {
                    "instruction": str(text)[:400],
                    "distance_km": _num(maneuver.get("length")),
                    "duration_sec": _num(maneuver.get("time")),
                    "begin_index": begin_index,
                }
            )
    if len(coordinates) < 2:
        raise NavError(422, "no route")
    return {
        "profile": profile,
        "distance_km": _num(summary.get("length")),
        "duration_sec": _num(summary.get("time")),
        "coordinates": coordinates,
        "steps": steps,
    }


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
