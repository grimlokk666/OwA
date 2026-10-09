"""Pydantic models for Sovereign Overwatch API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    level: str
    message: str
    source: str


class TelemetryPoint(BaseModel):
    """Plaintext GPS / device health report from a mobile node."""

    ts: str
    deviceId: str = Field(..., min_length=1)
    callsign: str = Field(..., min_length=1)
    lat: float
    lon: float
    alt: Optional[float] = None
    accuracy: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    battery: Optional[float] = None
    charging: Optional[bool] = None
    source: Literal["capacitor", "geolocation", "cached"] = "geolocation"


class EncryptedTelemetryEnvelope(BaseModel):
    """AES-GCM envelope from the mobile client (sovereign-aes-gcm-v1)."""

    v: Literal["sovereign-aes-gcm-v1"]
    deviceId: str
    callsign: str
    iv: str
    ciphertext: str
    ts: str


class TelemetryIngestResponse(BaseModel):
    status: str
    accepted: int = 1
    queued_replay: bool = False


class HealthResponse(BaseModel):
    status: str
    sovereign_mode: bool = True


class POIResult(BaseModel):
    id: Any
    lat: Optional[float] = None
    lon: Optional[float] = None
    tags: Optional[dict[str, Any]] = None
