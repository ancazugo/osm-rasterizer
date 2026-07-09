"""Tests for OpenHistoricalMap date parsing and filtering."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point

from osm_rasterizer.ohm import filter_by_date, parse_ohm_date


def _gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    """Build a WGS84 GeoDataFrame with one point per row of attributes."""
    data = {key: [row.get(key) for row in rows] for row in rows for key in row}
    return gpd.GeoDataFrame(
        data, geometry=[Point(0, 0)] * len(rows), crs="EPSG:4326"
    )


class TestParseOhmDate:
    def test_full_date(self):
        assert parse_ohm_date("1975-01-01", pad="start") == (1975, 1, 1)
        assert parse_ohm_date("1975-01-01", pad="end") == (1975, 1, 1)

    def test_year_only_pads(self):
        assert parse_ohm_date("1975", pad="start") == (1975, 1, 1)
        assert parse_ohm_date("1975", pad="end") == (1975, 12, 31)

    def test_year_month_pads(self):
        assert parse_ohm_date("1975-06", pad="start") == (1975, 6, 1)
        assert parse_ohm_date("1975-06", pad="end") == (1975, 6, 31)

    def test_negative_year(self):
        assert parse_ohm_date("-0500", pad="start") == (-500, 1, 1)
        assert parse_ohm_date("-0500", pad="start") < parse_ohm_date("1975", pad="start")

    def test_approximate_tilde(self):
        assert parse_ohm_date("~1900", pad="start") == (1900, 1, 1)

    @pytest.mark.parametrize("value", ["unknown", "", "..", float("nan"), 12.0, None, "1975-13", "1975-06-32"])
    def test_unparseable_returns_none(self, value):
        assert parse_ohm_date(value, pad="start") is None

    def test_lexicographic_pitfall(self):
        # As strings, "1975-01-01" > "1975"; as parsed keys they compare equal.
        assert parse_ohm_date("1975", pad="start") == parse_ohm_date("1975-01-01", pad="start")


class TestFilterByDate:
    def test_keeps_active_features(self):
        gdf = _gdf([{"start_date": "1850", "end_date": "1950"}])
        assert len(filter_by_date(gdf, "1900-06-15")) == 1

    def test_drops_not_yet_started(self):
        gdf = _gdf([{"start_date": "1950", "end_date": "2000"}])
        assert len(filter_by_date(gdf, "1900-06-15")) == 0

    def test_drops_ended(self):
        gdf = _gdf([{"start_date": "1800", "end_date": "1850"}])
        assert len(filter_by_date(gdf, "1900-06-15")) == 0

    def test_missing_start_date_kept(self):
        gdf = _gdf([{"start_date": None, "end_date": "1950"}])
        assert len(filter_by_date(gdf, "1900")) == 1

    def test_missing_end_date_kept(self):
        gdf = _gdf([{"start_date": "1850", "end_date": None}])
        assert len(filter_by_date(gdf, "1900")) == 1

    def test_no_date_columns_keeps_all(self):
        gdf = _gdf([{"building": "yes"}, {"building": "church"}])
        assert len(filter_by_date(gdf, "1900")) == 2

    def test_end_date_equal_query_kept(self):
        gdf = _gdf([{"start_date": "1850", "end_date": "1900-06-15"}])
        assert len(filter_by_date(gdf, "1900-06-15")) == 1

    def test_partial_end_date_covers_whole_year(self):
        gdf = _gdf([{"start_date": "1850", "end_date": "1900"}])
        assert len(filter_by_date(gdf, "1900-06-15")) == 1

    def test_mixed_rows_filtered_row_wise(self):
        gdf = _gdf(
            [
                {"start_date": "1850", "end_date": "1950"},
                {"start_date": "1950", "end_date": None},
                {"start_date": None, "end_date": "1800"},
            ]
        )
        assert len(filter_by_date(gdf, "1900")) == 1

    def test_datetime_query_uses_date_part(self):
        gdf = _gdf([{"start_date": "1850", "end_date": "1950"}])
        assert len(filter_by_date(gdf, "1900-06-15T12:00:00Z")) == 1

    def test_empty_gdf_returned_as_is(self, empty_gdf):
        assert filter_by_date(empty_gdf, "1900").empty

    def test_bad_query_date_raises(self):
        gdf = _gdf([{"start_date": "1850"}])
        with pytest.raises(ValueError, match="Invalid date"):
            filter_by_date(gdf, "sometime")

    def test_preserves_crs(self):
        gdf = _gdf([{"start_date": "1850", "end_date": "1950"}])
        assert filter_by_date(gdf, "1900").crs == "EPSG:4326"
