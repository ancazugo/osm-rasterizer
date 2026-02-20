"""Tests for osm_rasterizer.rasterize."""

from __future__ import annotations

import warnings
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import Polygon

from osm_rasterizer.rasterize import (
    RasterizeResult,
    _auto_name,
    _normalize_features,
    rasterize,
)

LONDON_BBOX = (-0.13, 51.49, -0.11, 51.51)


def _make_gdf(geoms=None) -> gpd.GeoDataFrame:
    if geoms is None:
        poly = Polygon([(-0.125, 51.495), (-0.115, 51.495), (-0.115, 51.505), (-0.125, 51.505)])
        geoms = [poly]
    return gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326")


def _empty_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


# ── _auto_name ──────────────────────────────────────────────────────────────

class TestAutoName:
    def test_bool_value(self):
        assert _auto_name({"building": True}, 0) == "building"

    def test_string_value(self):
        assert _auto_name({"highway": "residential"}, 0) == "highway_residential"

    def test_empty_dict(self):
        assert _auto_name({}, 3) == "feature_3"


# ── _normalize_features ─────────────────────────────────────────────────────

class TestNormalizeFeatures:
    def test_bare_dicts(self):
        result = _normalize_features([{"building": True}, {"highway": "residential"}])
        assert result == [("building", {"building": True}), ("highway_residential", {"highway": "residential"})]

    def test_named_tuples(self):
        result = _normalize_features([("bldgs", {"building": True})])
        assert result == [("bldgs", {"building": True})]

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _normalize_features([])

    def test_mixed_raises(self):
        with pytest.raises(TypeError, match="mix"):
            _normalize_features([{"building": True}, ("roads", {"highway": True})])


# ── rasterize() ─────────────────────────────────────────────────────────────

class TestRasterize:
    def test_invalid_bbox_x(self):
        with pytest.raises(ValueError, match="minx must be < maxx"):
            rasterize(bbox=(0.0, 0.0, 0.0, 1.0), features=[{"building": True}])

    def test_invalid_bbox_y(self):
        with pytest.raises(ValueError, match="miny must be < maxy"):
            rasterize(bbox=(0.0, 1.0, 1.0, 0.0), features=[{"building": True}])

    def test_empty_features_raises(self):
        with pytest.raises(ValueError, match="empty"):
            rasterize(bbox=LONDON_BBOX, features=[])

    def test_returns_rasterize_result(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert isinstance(result, RasterizeResult)

    def test_array_shape_single_feature(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert result.array.ndim == 3
        assert result.array.shape[0] == 1  # 1 band

    def test_array_dtype_uint8(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert result.array.dtype == np.uint8

    def test_multi_band(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}, {"highway": True}],
                resolution=50.0,
            )
        assert result.array.shape[0] == 2

    def test_single_layer(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}, {"highway": True}],
                resolution=50.0,
                single_layer=True,
            )
        assert result.array.shape[0] == 1
        assert result.band_names == ["merged"]

    def test_band_names_auto(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}, {"highway": "residential"}],
                resolution=50.0,
            )
        assert result.band_names == ["building", "highway_residential"]

    def test_band_names_named_tuples(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[("bldgs", {"building": True}), ("roads", {"highway": True})],
                resolution=50.0,
            )
        assert result.band_names == ["bldgs", "roads"]

    def test_empty_feature_warns_and_zero_band(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_empty_gdf()):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
            assert len(w) == 1
            assert "zero band" in str(w[0].message).lower() or "No features" in str(w[0].message)
        assert result.array.sum() == 0

    def test_crs_is_rasterio_crs(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert isinstance(result.crs, rasterio.CRS)

    def test_nodata_is_zero(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert result.nodata == 0

    def test_burned_pixels_nonzero(self):
        """At least some pixels should be 1 when features cover the bbox."""
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert result.array.max() == 1

    def test_writes_geotiff(self, tmp_path):
        out = tmp_path / "out.tif"
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            ret = rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}],
                resolution=50.0,
                output_path=out,
            )
        assert ret is None
        assert out.exists()
        with rasterio.open(out) as src:
            assert src.count == 1
            assert src.tags()["BAND_NAMES"] == "building"

    def test_geotiff_band_tag(self, tmp_path):
        out = tmp_path / "out.tif"
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            rasterize(
                bbox=LONDON_BBOX,
                features=[("myband", {"building": True})],
                resolution=50.0,
                output_path=out,
            )
        with rasterio.open(out) as src:
            assert src.tags(1)["name"] == "myband"

    def test_custom_crs(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}],
                resolution=50.0,
                crs="EPSG:32630",
            )
        assert result.crs.to_epsg() == 32630


@pytest.mark.integration
def test_integration_rasterize():
    """Integration: full pipeline against live Overpass for a small London bbox."""
    result = rasterize(
        bbox=(-0.13, 51.49, -0.11, 51.51),
        features=[{"building": True}, {"highway": True}],
        resolution=10.0,
    )
    assert isinstance(result, RasterizeResult)
    assert result.array.shape[0] == 2
    assert result.array.max() == 1
