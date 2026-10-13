"""Ohio OHGO public traffic cameras. Optional key, 120s cache, no open proxy."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("TrafficCams")

CACHE_SECONDS = 120
MAX_PAGES = 20
PAGE_SIZE = 500


def api_key() -> str:
    return os.getenv("OHGO_API_KEY", "").strip()


def api_url() -> str:
    return os.getenv(
        "OHGO_API_URL", "https://publicapi.ohgo.com/api/v1/cameras"
    ).strip()


_cache: dict[str, Any] = {"ts": 0.0, "key": "", "items": [], "status": "empty"}


def reset_cache() -> None:
    _cache["ts"] = 0.0
    _cache["key"] = ""
    _cache["items"] = []
    _cache["status"] = "empty"


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("results", "Results", "cameras", "Cameras"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _page_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 1
    for key in ("totalPageCount", "TotalPageCount"):
        if payload.get(key) is None:
            continue
        try:
            return max(1, int(payload[key]))
        except (TypeError, ValueError):
            return 1
    return 1


def normalize_ohgo(payload: Any) -> list[dict[str, Any]]:
    """Flatten OHGO camera sites into one record per view."""
    items: list[dict[str, Any]] = []
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        lat = _pick(row, "latitude", "Latitude", "lat")
        lon = _pick(row, "longitude", "Longitude", "lon")
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        site_id = str(_pick(row, "id", "Id") or "")
        place = str(
            _pick(row, "location", "Location", "description", "Description") or "Camera"
        )
        views = _pick(row, "cameraViews", "CameraViews", "cameras", "Cameras")
        if not isinstance(views, list) or not views:
            views = [row]
        for index, view in enumerate(views):
            if not isinstance(view, dict):
                continue
            url = _pick(
                view,
                "smallUrl",
                "SmallUrl",
                "largeUrl",
                "LargeUrl",
                "snapshot_url",
                "imageUrl",
            )
            if not url:
                url = _pick(row, "smallUrl", "SmallUrl", "largeUrl", "LargeUrl")
            if not url or not _is_public_https(str(url)):
                continue
            view_id = str(_pick(view, "id", "Id") or "")
            camera_id = view_id or (f"{site_id}-{index}" if site_id else f"cam-{index}")
            direction = str(_pick(view, "direction", "Direction") or "").strip()
            route = str(
                _pick(view, "mainRoute", "MainRoute")
                or _pick(row, "route", "Route", "mainRoute", "MainRoute")
                or ""
            )
            name = f"{place} {direction}".strip()
            items.append(
                {
                    "id": camera_id[:64],
                    "name": name[:160],
                    "lat": lat_f,
                    "lon": lon_f,
                    "route": route[:64],
                    "direction": direction[:32],
                    "snapshot_url": str(url),
                }
            )
    return items


def _is_public_https(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    host = parsed.hostname.strip("[]").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(ip.is_global)


def _host_is_public(hostname: str) -> bool:
    host = hostname.strip("[]").lower()
    if host in {"localhost"} or host.endswith(".local"):
        return False
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for info in addresses:
        ip_text = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


async def catalog() -> tuple[bool, str, list[dict[str, Any]]]:
    """Return (configured, status, cameras). Successful payloads are cached 120s."""
    key = api_key()
    if not key:
        return False, "no api key", []
    now = time.time()
    fresh = (
        _cache["key"] == key
        and _cache["status"] != "empty"
        and now - float(_cache["ts"]) < CACHE_SECONDS
    )
    if fresh:
        return True, str(_cache["status"]), list(_cache["items"])
    items, status = await _fetch_all(key)
    if status == "ok":
        _cache["ts"] = now
        _cache["key"] = key
        _cache["items"] = items
        _cache["status"] = status
        return True, status, list(items)
    if _cache["items"] and _cache["key"] == key:
        # Serve the last good catalog and back off for another cache window.
        _cache["ts"] = now
        _cache["status"] = status
        return True, status, list(_cache["items"])
    _cache["ts"] = now
    _cache["key"] = key
    _cache["items"] = []
    _cache["status"] = status
    return True, status, []


async def _fetch_all(key: str) -> tuple[list[dict[str, Any]], str]:
    url = api_url()
    headers = {"Authorization": f"APIKEY {key}", "Accept": "application/json"}
    collected: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            page = 1
            total_pages = 1
            while page <= total_pages and page <= MAX_PAGES:
                response = await client.get(
                    url,
                    headers=headers,
                    params={"page-number": page, "page-size": PAGE_SIZE},
                )
                if response.status_code in {401, 403}:
                    logger.info("OHGO rejected the API key")
                    return [], "unauthorized"
                if response.status_code >= 400:
                    logger.info("OHGO cameras HTTP %s", response.status_code)
                    return [], "unavailable"
                payload = response.json()
                collected.extend(normalize_ohgo(payload))
                total_pages = _page_count(payload)
                if not _rows(payload):
                    break
                page += 1
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("OHGO cameras unavailable: %s", type(exc).__name__)
        return [], "unavailable"
    # De-dupe by id, keep first view.
    unique: dict[str, dict[str, Any]] = {}
    for item in collected:
        unique.setdefault(item["id"], item)
    return list(unique.values()), "ok"


async def nearby(lat: float, lon: float, radius_km: float) -> dict[str, Any]:
    configured, status, items = await catalog()
    if not configured:
        return {"configured": False, "status": status, "cameras": []}
    ranked: list[dict[str, Any]] = []
    for item in items:
        dist = haversine_km(lat, lon, item["lat"], item["lon"])
        if dist > radius_km:
            continue
        ranked.append(
            {
                "id": item["id"],
                "name": item["name"],
                "lat": item["lat"],
                "lon": item["lon"],
                "route": item["route"],
                "direction": item["direction"],
                "distance_km": round(dist, 2),
            }
        )
    ranked.sort(key=lambda row: row["distance_km"])
    return {"configured": True, "status": status, "cameras": ranked[:100]}


def snapshot_target(camera_id: str) -> str | None:
    if not camera_id or _cache["key"] != api_key():
        return None
    for item in _cache["items"]:
        if item["id"] == camera_id:
            url = str(item["snapshot_url"])
            return url if _is_public_https(url) else None
    return None


async def fetch_snapshot(camera_id: str) -> tuple[bytes, str]:
    """Fetch a cached camera's snapshot. Refuses non-public URLs."""
    if not api_key():
        raise LookupError("no api key")
    # Refresh the catalog if the cache is cold so a snap after list still works.
    if not _cache["items"] or time.time() - float(_cache["ts"]) >= CACHE_SECONDS:
        await catalog()
    url = snapshot_target(camera_id)
    if not url:
        raise KeyError(camera_id)
    parsed = urlparse(url)
    if not _host_is_public(parsed.hostname or ""):
        raise PermissionError("snapshot host is not public")
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        response = await client.get(url, headers={"Accept": "image/*"})
    if response.status_code in {301, 302, 303, 307, 308}:
        raise PermissionError("snapshot redirects are not followed")
    if response.status_code >= 400:
        raise RuntimeError("snapshot upstream failed")
    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        raise RuntimeError("snapshot was not an image")
    body = response.content
    if len(body) > 5_000_000:
        raise RuntimeError("snapshot too large")
    return body, content_type
