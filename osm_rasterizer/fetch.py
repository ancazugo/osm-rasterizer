from __future__ import annotations

import geopandas as gpd
import osmnx as ox
from shapely.geometry import box

from .ohm import OHM_OVERPASS_URL, filter_by_date

try:
    from osmnx._errors import InsufficientResponseError
except ImportError:
    # osmnx < 2.0 fallback name
    from osmnx.errors import InsufficientResponseError  # type: ignore[no-redef]

VALID_PROVIDERS = ("osm", "ohm")


def fetch_features(
    bbox: tuple[float, float, float, float],
    tags: dict,
    date: str | None = None,
    provider: str = "osm",
) -> gpd.GeoDataFrame:
    """Fetch OSM or OpenHistoricalMap features for a WGS84 bounding box.

    Parameters
    ----------
    bbox:
        ``(minx, miny, maxx, maxy)`` in WGS84 degrees.
    tags:
        Tag dict in osmnx convention, e.g. ``{"building": True}``.  OHM uses
        the OSM tag vocabulary, so the same dicts work for both providers.
    date:
        Optional ISO 8601 date string (e.g. ``"2020-01-01"`` or
        ``"2020-01-01T00:00:00Z"``).  With ``provider="osm"`` this queries
        the OSM database as it existed at that point in time via the
        Overpass ``[date:"..."]`` filter.  With ``provider="ohm"`` it selects
        features that existed in the real world at that date, by filtering
        on their ``start_date``/``end_date`` tags (features without a
        ``start_date`` are treated as always existing); partial dates
        (``"1900"``) and BCE years (``"-0500"``) are supported.
    provider:
        ``"osm"`` (OpenStreetMap, default) or ``"ohm"`` (OpenHistoricalMap).

    Returns
    -------
    geopandas.GeoDataFrame
        Features clipped to the exact bbox polygon.  Returns an empty
        GeoDataFrame (with a geometry column) if no features are found.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"provider must be one of {VALID_PROVIDERS}, got {provider!r}")

    minx, miny, maxx, maxy = bbox

    original_settings = ox.settings.overpass_settings
    original_url = ox.settings.overpass_url
    if provider == "ohm":
        # OHM's [date:] selects database edit history, not historical
        # reality, so the date is applied post-fetch via start_date/end_date.
        ox.settings.overpass_url = OHM_OVERPASS_URL
    elif date:
        dt = date if "T" in date else f"{date}T00:00:00Z"
        ox.settings.overpass_settings = f'[out:json][timeout:180][date:"{dt}"]'

    # osmnx 2.x uses (west, south, east, north) = (minx, miny, maxx, maxy),
    # which matches our convention directly. osmnx 1.x used (north, south, east, west).
    try:
        gdf = ox.features_from_bbox(bbox=(minx, miny, maxx, maxy), tags=tags)
    except InsufficientResponseError:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    finally:
        ox.settings.overpass_settings = original_settings
        ox.settings.overpass_url = original_url

    if provider == "ohm" and date:
        gdf = filter_by_date(gdf, date)

    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    # Clip to exact bbox to remove any features partially outside
    clip_poly = box(minx, miny, maxx, maxy)
    return gdf.clip(clip_poly)
