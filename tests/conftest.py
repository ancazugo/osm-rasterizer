"""Shared test fixtures."""

from __future__ import annotations

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

# Small central London bbox (minx, miny, maxx, maxy)
LONDON_BBOX = (-0.13, 51.49, -0.11, 51.51)


@pytest.fixture
def london_bbox() -> tuple[float, float, float, float]:
    return LONDON_BBOX


@pytest.fixture
def simple_polygon_gdf() -> gpd.GeoDataFrame:
    """A GeoDataFrame with a single square polygon in WGS84."""
    poly = Polygon([(-0.125, 51.495), (-0.115, 51.495), (-0.115, 51.505), (-0.125, 51.505)])
    return gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")


@pytest.fixture
def simple_line_gdf() -> gpd.GeoDataFrame:
    """A GeoDataFrame with a single line in WGS84."""
    line = LineString([(-0.125, 51.495), (-0.115, 51.505)])
    return gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326")


@pytest.fixture
def empty_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
