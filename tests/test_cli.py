"""Tests for osm_rasterizer.cli."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from osm_rasterizer.cli import app, _parse_feature

runner = CliRunner()


# ── _parse_feature ───────────────────────────────────────────────────────────

class TestParseFeature:
    def test_bare_dict(self):
        result = _parse_feature('{"building": true}')
        assert result == {"building": True}

    def test_named_tuple(self):
        result = _parse_feature('buildings:{"building": true}')
        assert result == ("buildings", {"building": True})

    def test_named_with_space_before_brace(self):
        result = _parse_feature('my roads: {"highway": "residential"}')
        # The name is everything before '{'  stripped of trailing ':'
        name, tags = result
        assert tags == {"highway": "residential"}
        assert "roads" in name

    def test_no_brace_raises(self):
        import typer
        with pytest.raises(typer.BadParameter):
            _parse_feature("no_json_here")

    def test_invalid_json_raises(self):
        import typer
        with pytest.raises(typer.BadParameter):
            _parse_feature("{bad json}")


# ── CLI integration ──────────────────────────────────────────────────────────

class TestCli:
    def _patch_rasterize(self):
        return patch("osm_rasterizer.cli.rasterize", return_value=None)

    def test_basic_invocation(self, tmp_path):
        out = str(tmp_path / "out.tif")
        with self._patch_rasterize() as mock_rast:
            result = runner.invoke(
                app,
                [
                    "--bbox", "-0.13,51.49,-0.11,51.51",
                    "--feature", '{"building": true}',
                    "--output", out,
                    "--resolution", "50",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_rast.assert_called_once()

    def test_multi_feature(self, tmp_path):
        out = str(tmp_path / "out.tif")
        with self._patch_rasterize() as mock_rast:
            result = runner.invoke(
                app,
                [
                    "--bbox", "-0.13,51.49,-0.11,51.51",
                    "--feature", '{"building": true}',
                    "--feature", '{"highway": true}',
                    "--output", out,
                ],
            )
        assert result.exit_code == 0, result.output
        call_kwargs = mock_rast.call_args[1]
        assert len(call_kwargs["features"]) == 2

    def test_single_layer_flag(self, tmp_path):
        out = str(tmp_path / "out.tif")
        with self._patch_rasterize() as mock_rast:
            result = runner.invoke(
                app,
                [
                    "--bbox", "-0.13,51.49,-0.11,51.51",
                    "--feature", '{"building": true}',
                    "--output", out,
                    "--single-layer",
                ],
            )
        assert result.exit_code == 0, result.output
        call_kwargs = mock_rast.call_args[1]
        assert call_kwargs["single_layer"] is True

    def test_named_feature(self, tmp_path):
        out = str(tmp_path / "out.tif")
        with self._patch_rasterize() as mock_rast:
            result = runner.invoke(
                app,
                [
                    "--bbox", "-0.13,51.49,-0.11,51.51",
                    "--feature", 'bldgs:{"building": true}',
                    "--output", out,
                ],
            )
        assert result.exit_code == 0, result.output
        call_kwargs = mock_rast.call_args[1]
        assert call_kwargs["features"][0] == ("bldgs", {"building": True})

    def test_bad_bbox_exits_nonzero(self, tmp_path):
        out = str(tmp_path / "out.tif")
        result = runner.invoke(
            app,
            ["--bbox", "bad,bbox,here", "--feature", '{"building": true}', "--output", out],
        )
        assert result.exit_code != 0

    def test_crs_passed_through(self, tmp_path):
        out = str(tmp_path / "out.tif")
        with self._patch_rasterize() as mock_rast:
            result = runner.invoke(
                app,
                [
                    "--bbox", "-0.13,51.49,-0.11,51.51",
                    "--feature", '{"building": true}',
                    "--output", out,
                    "--crs", "EPSG:32630",
                ],
            )
        assert result.exit_code == 0, result.output
        call_kwargs = mock_rast.call_args[1]
        assert call_kwargs["crs"] == "EPSG:32630"
