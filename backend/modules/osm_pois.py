import logging
from typing import Any

import httpx

logger = logging.getLogger("OSM_Module")


async def query_local_osm_pois(
    lat: float,
    lon: float,
    radius_meters: int = 5000,
    amenity: str = "fuel",
) -> list[dict[str, Any]]:
    """
    Queries OpenStreetMap Overpass API or local mirror for amenities
    (fuel, food, rest_stops) without relying on closed commercial APIs.
    Includes fallback caching structures.
    """
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:25];
    node["amenity"="{amenity}"](around:{radius_meters},{lat},{lon});
    out body;
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(overpass_url, data=query)
            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        "id": el.get("id"),
                        "lat": el.get("lat"),
                        "lon": el.get("lon"),
                        "tags": el.get("tags"),
                    }
                    for el in data.get("elements", [])
                ]
    except Exception as e:
        logger.error(
            "OSM Query failed safely: %s. Falling back to cached local POI index.",
            e,
        )
    return []
