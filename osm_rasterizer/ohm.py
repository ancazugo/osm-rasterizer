"""OpenHistoricalMap (OHM) support: endpoint and start_date/end_date filtering.

Unlike OSM's Overpass API, where ``[date:"..."]`` selects a historical
database state, OHM models historical reality directly: features carry
``start_date`` / ``end_date`` tags describing when they existed in the real
world. Querying OHM "as of" a date therefore means fetching normally and
filtering features by those tags.
"""

from __future__ import annotations

import re
from typing import Literal

import geopandas as gpd

OHM_OVERPASS_URL = "https://overpass-api.openhistoricalmap.org/api"

# ISO 8601-ish date, possibly partial (YYYY, YYYY-MM) and possibly BCE
# (leading minus on the year, e.g. "-0500").
_DATE_RE = re.compile(r"^(-?\d{1,4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")


def parse_ohm_date(
    value: object, *, pad: Literal["start", "end"]
) -> tuple[int, int, int] | None:
    """Parse an OHM date value into a comparable ``(year, month, day)`` tuple.

    Returns ``None`` for missing/unparseable values (non-strings such as the
    NaN a GeoDataFrame yields for absent tags, empty strings, or EDTF oddities
    like ``".."``), meaning "no constraint".

    Partial dates are padded to their earliest (``pad="start"``) or latest
    (``pad="end"``) instant; the day is padded uniformly to 31, which
    over-includes by up to 3 days in short months — acceptable under the
    maximal-inclusion semantics used for filtering. A leading ``~``
    (approximate date) is ignored. Comparing int tuples instead of strings
    avoids the lexicographic pitfall where ``"1975-01-01"`` sorts after
    ``"1975"`` and handles BCE (negative) years correctly.
    """
    if not isinstance(value, str):
        return None

    match = _DATE_RE.match(value.strip().lstrip("~"))
    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None

    if month is not None and not 1 <= month <= 12:
        return None
    if day is not None and not 1 <= day <= 31:
        return None

    if pad == "start":
        return (year, month or 1, day or 1)
    return (year, month or 12, day or 31)


def filter_by_date(gdf: gpd.GeoDataFrame, date: str) -> gpd.GeoDataFrame:
    """Filter OHM features to those that existed at ``date``.

    A feature is kept iff ``start_date <= date`` and ``end_date >= date``,
    where a missing ``start_date`` means "always existed", a missing
    ``end_date`` means "still exists", and unparseable values impose no
    constraint (maximal inclusion).
    """
    query = parse_ohm_date(date.split("T")[0], pad="start")
    if query is None:
        raise ValueError(
            f"Invalid date {date!r}: expected ISO 8601, e.g. '1900', '1900-06' or '1900-06-15'"
        )

    if gdf.empty:
        return gdf

    def row_active(start: object, end: object) -> bool:
        start_key = parse_ohm_date(start, pad="start")
        end_key = parse_ohm_date(end, pad="end")
        return (start_key is None or start_key <= query) and (
            end_key is None or end_key >= query
        )

    starts = gdf["start_date"] if "start_date" in gdf.columns else [None] * len(gdf)
    ends = gdf["end_date"] if "end_date" in gdf.columns else [None] * len(gdf)
    mask = [row_active(s, e) for s, e in zip(starts, ends)]
    return gdf[mask]
