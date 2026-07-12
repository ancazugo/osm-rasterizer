"""Tests for osm_rasterizer.rasterize."""

from __future__ import annotations

import warnings
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import LineString, Polygon

from osm_rasterizer.rasterize import (
    LANE_WIDTH_M,
    RasterizeResult,
    _apply_filter,
    _auto_name,
    _fill_nodata_consensus,
    _normalize_features,
    _parse_width_tag,
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


def _line_gdf(**columns) -> gpd.GeoDataFrame:
    """A single-line GeoDataFrame with optional tag columns (e.g. width='12')."""
    line = LineString([(-0.125, 51.495), (-0.115, 51.505)])
    data = {k: [v] for k, v in columns.items()}
    return gpd.GeoDataFrame(data, geometry=[line], crs="EPSG:4326")


def _attr_gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    """Build a GeoDataFrame of small polygons, one per attribute-dict row.

    Each row supplies attribute columns (``surface``, ``sport``, …); geometries
    are small non-overlapping squares inside ``LONDON_BBOX``.
    """
    geoms = []
    for i in range(len(rows)):
        x = -0.128 + 0.004 * i
        geoms.append(Polygon([(x, 51.495), (x + 0.003, 51.495), (x + 0.003, 51.505), (x, 51.505)]))
    keys = {k for r in rows for k in r}
    data = {k: [r.get(k) for r in rows] for k in keys}
    return gpd.GeoDataFrame(data, geometry=geoms, crs="EPSG:4326")


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
        assert result == [
            ("building", {"building": True}, {}),
            ("highway_residential", {"highway": "residential"}, {}),
        ]

    def test_named_tuples(self):
        result = _normalize_features([("bldgs", {"building": True})])
        assert result == [("bldgs", {"building": True}, {})]

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _normalize_features([])

    def test_mixed_raises(self):
        with pytest.raises(TypeError, match="mix"):
            _normalize_features([{"building": True}, ("roads", {"highway": True})])

    def test_options_tuple(self):
        result = _normalize_features([("roads", {"highway": True}, {"line_width": 8.0})])
        assert result == [("roads", {"highway": True}, {"line_width": 8.0})]

    def test_unknown_option_raises(self):
        with pytest.raises(ValueError, match="unknown feature option"):
            _normalize_features([("roads", {"highway": True}, {"buffer": 8.0})])

    def test_non_dict_options_raises(self):
        with pytest.raises(TypeError, match="must be a dict"):
            _normalize_features([("roads", {"highway": True}, 8.0)])

    def test_bad_tuple_length_raises(self):
        with pytest.raises(TypeError, match="tuple of length"):
            _normalize_features([("roads", {"highway": True}, {}, "extra")])


# ── _parse_width_tag ────────────────────────────────────────────────────────

class TestParseWidthTag:
    def test_integer_string(self):
        assert _parse_width_tag("12") == 12.0

    def test_float_string(self):
        assert _parse_width_tag("12.5") == 12.5

    def test_metre_suffix(self):
        assert _parse_width_tag("12 m") == 12.0
        assert _parse_width_tag("12m") == 12.0

    def test_numeric_value(self):
        assert _parse_width_tag(7) == 7.0
        assert _parse_width_tag(7.5) == 7.5

    def test_unparseable_returns_none(self):
        assert _parse_width_tag("narrow") is None
        assert _parse_width_tag("3'6\"") is None

    def test_none_returns_none(self):
        assert _parse_width_tag(None) is None

    def test_nan_returns_none(self):
        assert _parse_width_tag(float("nan")) is None

    def test_non_positive_returns_none(self):
        assert _parse_width_tag("0") is None
        assert _parse_width_tag("-3") is None


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

    def test_provider_passed_to_fetch(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()) as mock_fetch:
            rasterize(
                bbox=LONDON_BBOX,
                features=[{"building": True}],
                resolution=50.0,
                provider="ohm",
            )
        assert mock_fetch.call_args.kwargs["provider"] == "ohm"

    def test_provider_defaults_to_osm(self):
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=_make_gdf()) as mock_fetch:
            rasterize(bbox=LONDON_BBOX, features=[{"building": True}], resolution=50.0)
        assert mock_fetch.call_args.kwargs["provider"] == "osm"

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


# ── rasterize() line widths ──────────────────────────────────────────────────

class TestLineWidths:
    def _burned(self, gdf, options=None) -> int:
        """Rasterize one feature over the London bbox and return the burned pixel count."""
        spec = ("road", {"highway": True}) if options is None else ("road", {"highway": True}, options)
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=gdf):
            result = rasterize(bbox=LONDON_BBOX, features=[spec], resolution=10.0)
        return int((result.array > 0).sum())

    def test_unbuffered_line_is_thin(self):
        # Without options a line burns as a ~1-pixel-wide trace
        count = self._burned(_line_gdf())
        assert 0 < count < 500

    def test_line_width_widens_line(self):
        thin = self._burned(_line_gdf())
        wide = self._burned(_line_gdf(), {"line_width": 50.0})
        # 50 m width at 10 m resolution ≈ 5 pixels wide
        assert wide > 3 * thin

    def test_wider_burns_more(self):
        w20 = self._burned(_line_gdf(), {"line_width": 20.0})
        w100 = self._burned(_line_gdf(), {"line_width": 100.0})
        assert w100 > w20

    def test_width_tag_used(self):
        from_tag = self._burned(_line_gdf(width="30"), {"width_from_tags": True})
        fixed = self._burned(_line_gdf(), {"line_width": 30.0})
        assert from_tag == fixed

    def test_width_tag_beats_line_width(self):
        from_tag = self._burned(_line_gdf(width="100"), {"width_from_tags": True, "line_width": 20.0})
        fixed = self._burned(_line_gdf(), {"line_width": 100.0})
        assert from_tag == fixed

    def test_lanes_fallback(self):
        from_lanes = self._burned(_line_gdf(lanes="4"), {"width_from_tags": True})
        fixed = self._burned(_line_gdf(), {"line_width": 4 * LANE_WIDTH_M})
        assert from_lanes == fixed

    def test_unparseable_tags_fall_back_to_line_width(self):
        junk = self._burned(_line_gdf(width="narrow", lanes="many"), {"width_from_tags": True, "line_width": 50.0})
        fixed = self._burned(_line_gdf(), {"line_width": 50.0})
        assert junk == fixed

    def test_no_resolvable_width_stays_thin(self):
        thin = self._burned(_line_gdf())
        tags_only = self._burned(_line_gdf(), {"width_from_tags": True})
        assert tags_only == thin

    def test_polygons_not_buffered(self):
        plain = self._burned(_make_gdf())
        with_width = self._burned(_make_gdf(), {"line_width": 100.0})
        assert with_width == plain


# ── _apply_filter ────────────────────────────────────────────────────────────

class TestApplyFilter:
    def test_dict_membership(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}, {"surface": "grass"}])
        result = _apply_filter(gdf, {"surface": ["grass"]})
        assert list(result["surface"]) == ["grass", "grass"]

    def test_dict_string_value(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        result = _apply_filter(gdf, {"surface": "grass"})
        assert list(result["surface"]) == ["grass"]

    def test_dict_multi_value_split_on_semicolon(self):
        gdf = _attr_gdf([{"sport": "soccer;basketball"}, {"sport": "tennis"}])
        result = _apply_filter(gdf, {"sport": ["soccer"]})
        assert list(result["sport"]) == ["soccer;basketball"]

    def test_dict_and_across_columns(self):
        gdf = _attr_gdf([
            {"surface": "grass", "sport": "soccer"},
            {"surface": "grass", "sport": "tennis"},
            {"surface": "asphalt", "sport": "soccer"},
        ])
        result = _apply_filter(gdf, {"surface": ["grass"], "sport": ["soccer"]})
        assert len(result) == 1
        assert result.iloc[0]["sport"] == "soccer"

    def test_dict_missing_column_drops_all(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        result = _apply_filter(gdf, {"sport": ["soccer"]})
        assert len(result) == 0

    def test_dict_nan_is_non_match(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": None}])
        result = _apply_filter(gdf, {"surface": ["grass"]})
        assert len(result) == 1

    def test_callable_returns_geodataframe(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        result = _apply_filter(gdf, lambda g: g[g["surface"] == "grass"])
        assert list(result["surface"]) == ["grass"]

    def test_callable_returns_boolean_mask(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        result = _apply_filter(gdf, lambda g: (g["surface"] == "grass").to_numpy())
        assert list(result["surface"]) == ["grass"]

    def test_callable_bad_return_raises(self):
        gdf = _attr_gdf([{"surface": "grass"}])
        with pytest.raises(TypeError, match="GeoDataFrame or a boolean row mask"):
            _apply_filter(gdf, lambda g: "nonsense")


# ── _normalize_features / _validate_options: filter & GeoDataFrame ───────────

class TestFilterAndGeoDataFrameNormalization:
    def test_filter_dict_option_accepted(self):
        result = _normalize_features([("p", {"leisure": "pitch"}, {"filter": {"surface": ["grass"]}})])
        assert result == [("p", {"leisure": "pitch"}, {"filter": {"surface": ["grass"]}})]

    def test_filter_callable_option_accepted(self):
        fn = lambda g: g
        result = _normalize_features([("p", {"leisure": "pitch"}, {"filter": fn})])
        assert result[0][2]["filter"] is fn

    def test_filter_bad_type_raises(self):
        with pytest.raises(TypeError, match="filter for .* must be a dict or a callable"):
            _normalize_features([("p", {"leisure": "pitch"}, {"filter": 42})])

    def test_filter_bad_value_type_raises(self):
        with pytest.raises(TypeError, match="must be a string or list of strings"):
            _normalize_features([("p", {"leisure": "pitch"}, {"filter": {"surface": [1, 2]}})])

    def test_geodataframe_feature_passes_through(self):
        gdf = _attr_gdf([{"surface": "grass"}])
        result = _normalize_features([("pitches", gdf)])
        assert result[0][0] == "pitches"
        assert result[0][1] is gdf
        assert result[0][2] == {}

    def test_bare_geodataframe_raises(self):
        gdf = _attr_gdf([{"surface": "grass"}])
        with pytest.raises(TypeError, match="must be named"):
            _normalize_features([gdf])


# ── rasterize() with filter and GeoDataFrame features ────────────────────────

class TestRasterizeFilterAndGeoDataFrame:
    def test_filter_narrows_fetched_rows(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=gdf):
            filtered = rasterize(
                bbox=LONDON_BBOX,
                features=[("grass", {"leisure": "pitch"}, {"filter": {"surface": ["grass"]}})],
                resolution=50.0,
            )
            unfiltered = rasterize(
                bbox=LONDON_BBOX,
                features=[("all", {"leisure": "pitch"})],
                resolution=50.0,
            )
        assert int((filtered.array > 0).sum()) < int((unfiltered.array > 0).sum())
        assert int((filtered.array > 0).sum()) > 0

    def test_filter_matching_nothing_warns_zero_band(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        with patch("osm_rasterizer.rasterize.fetch_features", return_value=gdf):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = rasterize(
                    bbox=LONDON_BBOX,
                    features=[("clay", {"leisure": "pitch"}, {"filter": {"surface": ["clay"]}})],
                    resolution=50.0,
                )
            assert len(w) == 1
            assert "after filter" in str(w[0].message)
        assert result.array.sum() == 0

    def test_geodataframe_feature_skips_fetch(self):
        gdf = _attr_gdf([{"surface": "grass"}])
        with patch("osm_rasterizer.rasterize.fetch_features") as mock_fetch:
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[("pitches", gdf)],
                resolution=50.0,
            )
        mock_fetch.assert_not_called()
        assert result.array.max() == 1

    def test_geodataframe_feature_respects_filter(self):
        gdf = _attr_gdf([{"surface": "grass"}, {"surface": "asphalt"}])
        with patch("osm_rasterizer.rasterize.fetch_features") as mock_fetch:
            result = rasterize(
                bbox=LONDON_BBOX,
                features=[("grass", gdf, {"filter": {"surface": ["grass"]}})],
                resolution=50.0,
            )
        mock_fetch.assert_not_called()
        assert result.array.max() == 1


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
