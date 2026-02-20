"""Tests for osm_rasterizer.crs."""

from __future__ import annotations

import pytest
import pyproj

from osm_rasterizer.crs import get_utm_crs


def test_london_returns_utm_zone_30(london_bbox):
    """Central London should map to UTM zone 30N (EPSG:32630)."""
    crs = get_utm_crs(london_bbox)
    assert isinstance(crs, pyproj.CRS)
    assert crs.is_projected
    # UTM zone 30N
    epsg = crs.to_epsg()
    assert epsg == 32630, f"Expected EPSG:32630, got EPSG:{epsg}"


def test_new_york_returns_utm_zone_18():
    """New York should map to UTM zone 18N (EPSG:32618)."""
    nyc_bbox = (-74.05, 40.70, -73.95, 40.80)
    crs = get_utm_crs(nyc_bbox)
    assert crs.is_projected
    epsg = crs.to_epsg()
    assert epsg == 32618, f"Expected EPSG:32618, got EPSG:{epsg}"


def test_returns_pyproj_crs(london_bbox):
    result = get_utm_crs(london_bbox)
    assert isinstance(result, pyproj.CRS)


def test_southern_hemisphere_returns_south_zone():
    """Sydney, Australia should return a south-hemisphere UTM zone."""
    sydney_bbox = (151.15, -33.90, 151.25, -33.80)
    crs = get_utm_crs(sydney_bbox)
    assert crs.is_projected
    # UTM zone 56S = EPSG:32756
    epsg = crs.to_epsg()
    assert epsg == 32756, f"Expected EPSG:32756, got EPSG:{epsg}"
