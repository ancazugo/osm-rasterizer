from __future__ import annotations

import geopandas as gpd
import osmnx as ox
from shapely.geometry import box

try:
    from osmnx._errors import InsufficientResponseError
except ImportError:
    # osmnx < 2.0 fallback name
    from osmnx.errors import InsufficientResponseError  # type: ignore[no-redef]


def fetch_features(
    bbox: tuple[float, float, float, float],
    tags: dict,
) -> gpd.GeoDataFrame:
    """Fetch OSM features for a WGS84 bounding box.

    Parameters
    ----------
    bbox:
        ``(minx, miny, maxx, maxy)`` in WGS84 degrees.
    tags:
        OSM tag dict in osmnx convention, e.g. ``{"building": True}``.

    Returns
    -------
    geopandas.GeoDataFrame
        Features clipped to the exact bbox polygon.  Returns an empty
        GeoDataFrame (with a geometry column) if no features are found.
    """
    minx, miny, maxx, maxy = bbox
    # osmnx expects (north, south, east, west) — opposite of our convention
    try:
        gdf = ox.features_from_bbox(bbox=(maxy, miny, maxx, minx), tags=tags)
    except InsufficientResponseError:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    # Clip to exact bbox to remove any features partially outside
    clip_poly = box(minx, miny, maxx, maxy)
    return gdf.clip(clip_poly)
