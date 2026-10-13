import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import get_db, init_db
from models import (
    AlertPayload,
    EncryptedTelemetryEnvelope,
    HealthResponse,
    TelemetryIngestResponse,
    TelemetryPoint,
)
from modules import adsb_tracker, osm_pois, scanner_proxy, traffic_cams
from modules.traccar_receiver import decrypt_envelope, persist_point

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OverwatchCore")


async def sovereign_background_worker():
    """Long-term background loop handling resilient polling and caching."""
    while True:
        try:
            # Placeholder for resilient background polling (DOT cams, ADS-B local dump1090)
            logger.info("Executing Sovereign D background maintenance and feed sync...")
            await adsb_tracker.fetch_local_aircraft()
        except Exception as e:
            logger.error(
                "Background worker encountered minor error (resiliently caught): %s", e
            )
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    worker_task = asyncio.create_task(sovereign_background_worker())
    yield
    worker_task.cancel()


app = FastAPI(title="Sovereign Overwatch API", version="1.0.0", lifespan=lifespan)

_cors = os.getenv("CORS_ORIGINS", "*")
_origins = ["*"] if _cors.strip() == "*" else [o.strip() for o in _cors.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "operational", "sovereign_mode": True}


@app.post("/api/alert")
async def trigger_alert(payload: AlertPayload):
    logger.warning(
        "ALERT [%s] from %s: %s",
        payload.level.upper(),
        payload.source,
        payload.message,
    )
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    webhook,
                    json={
                        "content": f"**[{payload.level.upper()}]** `{payload.source}`: {payload.message}"
                    },
                )
        except Exception as e:
            logger.error("Discord webhook failed (non-fatal): %s", e)
    return {"status": "alert_dispatched", "content": payload.message}


@app.post("/api/telemetry", response_model=TelemetryIngestResponse)
async def ingest_telemetry(payload: Any = Body(...)):
    """
    OwnTracks/Traccar-style ingest from the mobile companion.

    Accepts:
      - single TelemetryPoint JSON
      - batch list[TelemetryPoint] (IndexedDB replay flush)
      - EncryptedTelemetryEnvelope (sovereign-aes-gcm-v1)
    """
    items: list[dict[str, Any]] = []
    encrypted = False
    raw_envelope: str | None = None

    if isinstance(payload, list):
        items = [TelemetryPoint.model_validate(p).model_dump() for p in payload]
    elif isinstance(payload, dict) and payload.get("v") == "sovereign-aes-gcm-v1":
        envelope = EncryptedTelemetryEnvelope.model_validate(payload)
        encrypted = True
        raw_envelope = envelope.model_dump_json()
        decrypted = decrypt_envelope(envelope.model_dump())
        if decrypted is None:
            # Store ciphertext for later offline decrypt; still acknowledge
            items = [
                {
                    "ts": envelope.ts,
                    "deviceId": envelope.deviceId,
                    "callsign": envelope.callsign,
                    "lat": 0.0,
                    "lon": 0.0,
                    "source": "cached",
                }
            ]
        else:
            items = [TelemetryPoint.model_validate(decrypted).model_dump()]
    elif isinstance(payload, dict):
        items = [TelemetryPoint.model_validate(payload).model_dump()]
    else:
        raise HTTPException(status_code=400, detail="unsupported telemetry payload")

    if not items:
        raise HTTPException(status_code=400, detail="empty telemetry payload")

    async with get_db() as db:
        for point in items:
            await persist_point(
                db, point, encrypted=encrypted, raw_envelope=raw_envelope
            )

    logger.info(
        "Telemetry accepted device=%s callsign=%s points=%d encrypted=%s",
        items[0].get("deviceId"),
        items[0].get("callsign"),
        len(items),
        encrypted,
    )
    return TelemetryIngestResponse(status="ok", accepted=len(items))


@app.get("/api/telemetry/latest")
async def latest_telemetry(limit: int = 50):
    limit = max(1, min(limit, 500))
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT ts, device_id, callsign, lat, lon, alt, accuracy,
                   heading, speed, battery, charging, source, encrypted
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    return {
        "points": [
            {
                "ts": r["ts"],
                "deviceId": r["device_id"],
                "callsign": r["callsign"],
                "lat": r["lat"],
                "lon": r["lon"],
                "alt": r["alt"],
                "accuracy": r["accuracy"],
                "heading": r["heading"],
                "speed": r["speed"],
                "battery": r["battery"],
                "charging": bool(r["charging"]) if r["charging"] is not None else None,
                "source": r["source"],
                "encrypted": bool(r["encrypted"]),
            }
            for r in rows
        ]
    }


@app.get("/api/pois")
async def pois(lat: float, lon: float, radius: int = 5000, amenity: str = "fuel"):
    results = await osm_pois.query_local_osm_pois(lat, lon, radius, amenity)
    return {"results": results}


@app.get("/api/cameras")
async def cameras(lat: float, lon: float, radius_km: float = 25.0):
    return {"cameras": await traffic_cams.fetch_nearby_cameras(lat, lon, radius_km)}


@app.get("/api/adsb")
async def adsb():
    return {"aircraft": await adsb_tracker.fetch_local_aircraft()}


@app.get("/api/scanner")
async def scanner():
    return await scanner_proxy.stream_status()
