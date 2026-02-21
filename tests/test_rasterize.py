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
    _fill_nodata_consensus,
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
        assert result.band_names == ["landcover"]

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


# ── _fill_nodata_consensus ───────────────────────────────────────────────────

class TestFillNodataConsensus:
    def test_surrounded_zero_gets_filled(self):
        arr = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
        result = _fill_nodata_consensus(arr)
        assert result[1, 1] == 1

    def test_no_zeros_unchanged(self):
        arr = np.array([[1, 2], [3, 1]], dtype=np.uint8)
        result = _fill_nodata_consensus(arr)
        np.testing.assert_array_equal(result, arr)

    def test_all_zeros_stays_zero(self):
        arr = np.zeros((3, 3), dtype=np.uint8)
        result = _fill_nodata_consensus(arr)
        assert result.sum() == 0

    def test_nearest_label_propagated(self):
        # Top-left 2×2 block is zero; nearest non-zero is value 1 at (0,2)
        arr = np.array([[0, 0, 1], [0, 0, 2], [3, 3, 3]], dtype=np.uint8)
        result = _fill_nodata_consensus(arr)
        # Every pixel must be non-zero
        assert (result > 0).all()
        # The top-left corner is closest to (0,2)=1 or (1,2)=2 — either way
        # the result must be one of the existing labels, not 0.
        assert result[0, 0] in (1, 2, 3)

    def test_large_empty_region_fully_filled(self):
        # 5×5 array: only the edges have labels, centre 3×3 is empty
        arr = np.ones((5, 5), dtype=np.uint8)
        arr[1:4, 1:4] = 0
        result = _fill_nodata_consensus(arr)
        assert (result > 0).all()

    def test_max_distance_limits_fill(self):
        # 1-D-like row: labelled pixel at col 0, zero pixels at cols 1-4
        arr = np.array([[1, 0, 0, 0, 0]], dtype=np.uint8)
        result = _fill_nodata_consensus(arr, max_distance=2)
        # cols 1 and 2 are within distance 2 → filled
        assert result[0, 1] == 1
        assert result[0, 2] == 1
        # cols 3 and 4 are beyond distance 2 → stay 0
        assert result[0, 3] == 0
        assert result[0, 4] == 0

    def test_max_distance_none_fills_all(self):
        arr = np.array([[1, 0, 0, 0, 0]], dtype=np.uint8)
        result = _fill_nodata_consensus(arr, max_distance=None)
        assert (result > 0).all()

    def test_returns_uint8(self):
        arr = np.array([[1, 1], [1, 0]], dtype=np.uint8)
        result = _fill_nodata_consensus(arr)
        assert result.dtype == np.uint8

    def test_original_not_mutated(self):
        arr = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
        original = arr.copy()
        _fill_nodata_consensus(arr)
        np.testing.assert_array_equal(arr, original)


# ── rasterize() fill_nodata ──────────────────────────────────────────────────

class TestRasterizeFillNodata:
    def test_fill_nodata_false_preserves_zeros(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_empty_gdf()):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                result = rasterize(
                    bbox=LONDON_BBOX,
                    features=[{"building": True}],
                    resolution=50.0,
                    fill_nodata=False,
                )
        assert result.array.sum() == 0

    def test_fill_nodata_true_does_not_increase_zeros(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result_no_fill = rasterize(
                bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0, fill_nodata=False
            )
            result_fill = rasterize(
                bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0, fill_nodata=True
            )
        zeros_before = (result_no_fill.array == 0).sum()
        zeros_after = (result_fill.array == 0).sum()
        assert zeros_after <= zeros_before

    def test_fill_nodata_true_single_layer(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()):
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}, {"highway": True}],
                resolution=50.0,
                single_layer=True,
                fill_nodata=True,
            )
        assert isinstance(result, RasterizeResult)
        assert result.array.shape[0] == 1


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
