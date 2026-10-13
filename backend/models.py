"""Pydantic models for Sovereign Overwatch API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    level: str = Field(..., max_length=16)
    message: str = Field(..., max_length=1500)
    source: str = Field(..., max_length=64)


class TelemetryPoint(BaseModel):
    """Plaintext GPS / device health report from a mobile node."""

    ts: str = Field(..., min_length=10, max_length=40)
    deviceId: str = Field(..., min_length=1, max_length=64)
    callsign: str = Field(..., min_length=1, max_length=32)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    alt: Optional[float] = Field(None, ge=-1000, le=100000)
    accuracy: Optional[float] = Field(None, ge=0, le=1000000)
    heading: Optional[float] = Field(None, ge=-1, le=360)
    speed: Optional[float] = Field(None, ge=-1, le=2000)
    battery: Optional[float] = Field(None, ge=-1, le=100)
    charging: Optional[bool] = None
    source: Literal["capacitor", "geolocation", "cached"] = "geolocation"


class EncryptedTelemetryEnvelope(BaseModel):
    """AES-GCM envelope from the mobile client (sovereign-aes-gcm-v1)."""

    v: Literal["sovereign-aes-gcm-v1"]
    deviceId: str = Field(..., min_length=1, max_length=64)
    callsign: str = Field(..., min_length=1, max_length=32)
    iv: str = Field(..., max_length=64)
    ciphertext: str = Field(..., max_length=16384)
    ts: str = Field(..., max_length=40)


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
