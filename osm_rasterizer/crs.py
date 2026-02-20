from __future__ import annotations

import pyproj
from pyproj import CRS
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info


def get_utm_crs(bbox: tuple[float, float, float, float]) -> CRS:
    """Auto-detect best UTM CRS for a WGS84 bbox.

    Parameters
    ----------
    bbox:
        ``(minx, miny, maxx, maxy)`` in WGS84 (EPSG:4326).

    Returns
    -------
    pyproj.CRS
        The best-fit UTM CRS for the given bounding box.
    """
    minx, miny, maxx, maxy = bbox
    aoi = AreaOfInterest(
        west_lon_degree=minx,
        south_lat_degree=miny,
        east_lon_degree=maxx,
        north_lat_degree=maxy,
    )
    results = query_utm_crs_info(datum_name="WGS 84", area_of_interest=aoi)
    if not results:
        raise ValueError(f"No UTM CRS found for bbox {bbox}")
    best = results[0]
    return CRS.from_authority(best.auth_name, best.code)
