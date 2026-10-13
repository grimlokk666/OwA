"""Valhalla polyline6 decoder (precision 1e-6, lat/lon order)."""

from __future__ import annotations


def decode_polyline(encoded: str, precision: int = 6) -> list[tuple[float, float]]:
    """Decode an encoded polyline into (lat, lon) pairs."""
    if not encoded:
        return []
    scale = 10**precision
    lat = 0
    lon = 0
    coords: list[tuple[float, float]] = []
    index = 0
    length = len(encoded)
    while index < length:
        lat_delta, index = _delta(encoded, index)
        lon_delta, index = _delta(encoded, index)
        lat += lat_delta
        lon += lon_delta
        coords.append((lat / scale, lon / scale))
    return coords


def _delta(encoded: str, index: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if index >= len(encoded):
            raise ValueError("truncated polyline")
        byte = ord(encoded[index]) - 63
        index += 1
        result |= (byte & 0x1F) << shift
        shift += 5
        if byte < 0x20:
            break
    delta = ~(result >> 1) if result & 1 else (result >> 1)
    return delta, index
