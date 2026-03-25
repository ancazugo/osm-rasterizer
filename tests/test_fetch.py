"""Tests for osm_rasterizer.fetch."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from osm_rasterizer.fetch import fetch_features


LONDON_BBOX = (-0.13, 51.49, -0.11, 51.51)


def _make_gdf(geoms=None) -> gpd.GeoDataFrame:
    if geoms is None:
        poly = Polygon([(-0.125, 51.495), (-0.115, 51.495), (-0.115, 51.505), (-0.125, 51.505)])
        geoms = [poly]
    return gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326")


def test_returns_geodataframe(london_bbox):
    """fetch_features returns a GeoDataFrame (may be empty without network)."""
    with patch("osm_rasterizer.fetch.ox.features_from_bbox", return_value=_make_gdf()):
        result = fetch_features(london_bbox, {"building": True})
    assert isinstance(result, gpd.GeoDataFrame)


def test_bbox_order():
    """features_from_bbox must be called with osmnx 2.x (west, south, east, north) order."""
    minx, miny, maxx, maxy = LONDON_BBOX
    with patch("osm_rasterizer.fetch.ox.features_from_bbox", return_value=_make_gdf()) as mock_fn:
        fetch_features(LONDON_BBOX, {"building": True})
        _, kwargs = mock_fn.call_args
        called_bbox = kwargs["bbox"]
        # osmnx 2.x convention: (west, south, east, north) = (minx, miny, maxx, maxy)
        assert called_bbox == (minx, miny, maxx, maxy), (
            f"Expected bbox=(west={minx}, south={miny}, east={maxx}, north={maxy}), "
            f"got {called_bbox}"
        )


def test_empty_on_insufficient_response(london_bbox):
    """Returns empty GeoDataFrame when osmnx raises InsufficientResponseError."""
    try:
        from osmnx._errors import InsufficientResponseError
    except ImportError:
        from osmnx.errors import InsufficientResponseError

    with patch("osm_rasterizer.fetch.ox.features_from_bbox", side_effect=InsufficientResponseError()):
        result = fetch_features(london_bbox, {"building": True})

    assert isinstance(result, gpd.GeoDataFrame)
    assert result.empty


def test_result_clipped_to_bbox():
    """Features are clipped to the exact bbox polygon."""
    minx, miny, maxx, maxy = LONDON_BBOX
    # A polygon that extends beyond the bbox on all sides
    large_poly = Polygon([(minx - 1, miny - 1), (maxx + 1, miny - 1),
                           (maxx + 1, maxy + 1), (minx - 1, maxy + 1)])
    gdf = _make_gdf([large_poly])

    with patch("osm_rasterizer.fetch.ox.features_from_bbox", return_value=gdf):
        result = fetch_features(LONDON_BBOX, {"building": True})

    # All result geometries should be within the bbox (with small float tolerance)
    from shapely.geometry import box
    bbox_poly = box(minx, miny, maxx, maxy).buffer(1e-9)
    for geom in result.geometry:
        assert bbox_poly.contains(geom) or bbox_poly.covers(geom), (
            f"Geometry {geom} extends outside bbox"
        )


def test_empty_gdf_passthrough(london_bbox):
    """An empty response from osmnx is returned as an empty GeoDataFrame."""
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    with patch("osm_rasterizer.fetch.ox.features_from_bbox", return_value=empty):
        result = fetch_features(london_bbox, {"building": True})
    assert result.empty


def test_date_sets_overpass_filter():
    """A date argument injects [date:"..."] into the Overpass API settings."""
    import osmnx as ox

    with patch("osm_rasterizer.fetch.ox.features_from_bbox", return_value=_make_gdf()):
        fetch_features(LONDON_BBOX, {"building": True}, date="2020-01-01")

    # Settings should be restored after the call
    assert '[date:"' not in ox.settings.overpass_settings


def test_date_with_time_component():
    """A date string with a time component is passed through unchanged."""
    captured = {}

    def _capture_settings(*args, **kwargs):
        captured["settings"] = ox.settings.overpass_settings
        return _make_gdf()

    import osmnx as ox

    with patch("osm_rasterizer.fetch.ox.features_from_bbox", side_effect=_capture_settings):
        fetch_features(LONDON_BBOX, {"building": True}, date="2020-06-15T12:00:00Z")

    assert '[date:"2020-06-15T12:00:00Z"]' in captured["settings"]


def test_date_normalizes_bare_date():
    """A bare date (no time component) gets T00:00:00Z appended."""
    captured = {}

    def _capture_settings(*args, **kwargs):
        captured["settings"] = ox.settings.overpass_settings
        return _make_gdf()

    import osmnx as ox

    with patch("osm_rasterizer.fetch.ox.features_from_bbox", side_effect=_capture_settings):
        fetch_features(LONDON_BBOX, {"building": True}, date="2020-01-01")

    assert '[date:"2020-01-01T00:00:00Z"]' in captured["settings"]


def test_date_none_leaves_default_settings():
    """When date=None, overpass_settings are not modified."""
    import osmnx as ox

    original = ox.settings.overpass_settings
    with patch("osm_rasterizer.fetch.ox.features_from_bbox", return_value=_make_gdf()):
        fetch_features(LONDON_BBOX, {"building": True}, date=None)

    assert ox.settings.overpass_settings == original


def test_date_settings_restored_on_error():
    """overpass_settings are restored even if osmnx raises an exception."""
    import osmnx as ox

    original = ox.settings.overpass_settings
    try:
        from osmnx._errors import InsufficientResponseError
    except ImportError:
        from osmnx.errors import InsufficientResponseError

    with patch("osm_rasterizer.fetch.ox.features_from_bbox", side_effect=InsufficientResponseError()):
        fetch_features(LONDON_BBOX, {"building": True}, date="2020-01-01")

    assert ox.settings.overpass_settings == original


@pytest.mark.integration
def test_integration_buildings():
    """Integration: fetch real buildings from Overpass for a small bbox."""
    bbox = (-0.13, 51.49, -0.11, 51.51)
    result = fetch_features(bbox, {"building": True})
    assert isinstance(result, gpd.GeoDataFrame)
    assert not result.empty, "Expected buildings in central London"
