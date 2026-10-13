import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from database import get_db, init_db, maintenance
from models import (
    AlertPayload,
    EncryptedTelemetryEnvelope,
    HealthResponse,
    TelemetryIngestResponse,
    TelemetryPoint,
)
from modules import adsb_tracker, osm_pois, scanner_proxy, traffic_cams
from modules.traccar_receiver import decrypt_envelope, encryption_key_configured, persist_point

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OverwatchCore")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        logger.error("Invalid %s=%r; using %s", name, raw, default)
        return default


RETENTION_DAYS = _int_env("TELEMETRY_RETENTION_DAYS", 365)
BACKUP_KEEP = _int_env("BACKUP_KEEP", 14)
POI_CACHE_DAYS = _int_env("POI_CACHE_DAYS", 30)
REQUIRE_KEY = os.getenv("TELEMETRY_REQUIRE_KEY", "true").lower() == "true"
ALERT_TOKEN = os.getenv("ALERT_TOKEN", "").strip()
MAX_BATCH = 500


def _token_ok(presented: str) -> bool:
    if not ALERT_TOKEN:
        return False
    try:
        return hmac.compare_digest(
            presented.encode("utf-8"),
            ALERT_TOKEN.encode("utf-8"),
        )
    except Exception:
        return False


async def require_api_token(x_overwatch_token: str = Header(default="")) -> None:
    """Shared secret for alerts and read endpoints. Header: X-Overwatch-Token."""
    if not _token_ok(x_overwatch_token):
        raise HTTPException(status_code=401, detail="unauthorized")


async def maintenance_worker():
    """Daily retention + DB backup."""
    while True:
        try:
            await maintenance(RETENTION_DAYS, BACKUP_KEEP, POI_CACHE_DAYS)
            logger.info(
                "Maintenance done (retention=%sd, poi_cache=%sd, keep=%s backups)",
                RETENTION_DAYS,
                POI_CACHE_DAYS,
                BACKUP_KEEP,
            )
        except Exception as e:
            logger.error("Maintenance failed: %s", e)
        await asyncio.sleep(86400)


async def sovereign_background_worker():
    """Long-term background loop handling resilient polling and caching."""
    while True:
        try:
            # Placeholder for resilient background polling (DOT cams, ADS-B local dump1090)
            logger.debug("Background feed sync")
            await adsb_tracker.fetch_local_aircraft()
        except Exception as e:
            logger.error(
                "Background worker encountered minor error (resiliently caught): %s", e
            )
        await asyncio.sleep(60)


def _workers_enabled() -> bool:
    return os.getenv("OVERWATCH_DISABLE_WORKERS", "").lower() not in {"1", "true", "yes"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    tasks: list[asyncio.Task[None]] = []
    if _workers_enabled():
        tasks.append(asyncio.create_task(sovereign_background_worker()))
        tasks.append(asyncio.create_task(maintenance_worker()))
    yield
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Sovereign Overwatch API", version="1.0.0", lifespan=lifespan)

_cors = os.getenv("CORS_ORIGINS", "http://127.0.0.1:3012")
if _cors.strip() == "*":
    _origins = ["*"]
else:
    _origins = [o.strip() for o in _cors.split(",") if o.strip()]

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


@app.post("/api/alert", dependencies=[Depends(require_api_token)])
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
      - single TelemetryPoint JSON (rejected when TELEMETRY_REQUIRE_KEY is true)
      - batch list[TelemetryPoint] (IndexedDB replay flush; same key requirement)
      - EncryptedTelemetryEnvelope (sovereign-aes-gcm-v1)
    """
    try:
        return await _ingest(payload)
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_url=False, include_context=False, include_input=False),
        ) from e


async def _ingest(payload: Any) -> TelemetryIngestResponse:
    items: list[dict[str, Any]] = []
    encrypted = False
    raw_envelope: str | None = None
    is_env = isinstance(payload, dict) and payload.get("v") == "sovereign-aes-gcm-v1"
    if REQUIRE_KEY and not is_env:
        raise HTTPException(status_code=401, detail="encrypted envelope with shared key required")
    if isinstance(payload, list):
        if len(payload) > MAX_BATCH:
            raise HTTPException(status_code=413, detail="batch too large")
        items = [TelemetryPoint.model_validate(p).model_dump() for p in payload]
    elif is_env:
        envelope = EncryptedTelemetryEnvelope.model_validate(payload)
        encrypted = True
        raw_envelope = envelope.model_dump_json()
        if not encryption_key_configured():
            raise HTTPException(status_code=401, detail="encryption key not configured")
        decrypted = decrypt_envelope(envelope.model_dump())
        if decrypted is None:
            raise HTTPException(status_code=401, detail="bad key or corrupt envelope")
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


@app.get("/api/telemetry/latest", dependencies=[Depends(require_api_token)])
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


@app.get("/api/pois", dependencies=[Depends(require_api_token)])
async def pois(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: int = 5000,
    amenity: str = "fuel",
):
    radius = max(100, min(radius, 50000))
    amenity = "".join(ch for ch in amenity if ch.isalnum() or ch in "_:-")[:32] or "fuel"
    results = await osm_pois.query_local_osm_pois(lat, lon, radius, amenity)
    return {"results": results}


@app.get("/api/cameras", dependencies=[Depends(require_api_token)])
async def cameras(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = 25.0,
):
    radius_km = max(0.1, min(radius_km, 200.0))
    return {"cameras": await traffic_cams.fetch_nearby_cameras(lat, lon, radius_km)}


@app.get("/api/adsb", dependencies=[Depends(require_api_token)])
async def adsb():
    return {"aircraft": await adsb_tracker.fetch_local_aircraft()}


@app.get("/api/scanner", dependencies=[Depends(require_api_token)])
async def scanner():
    return await scanner_proxy.stream_status()
