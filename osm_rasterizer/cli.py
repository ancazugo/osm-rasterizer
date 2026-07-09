from __future__ import annotations

import json
from typing import Annotated, Optional

import typer
from rich.console import Console

from .rasterize import rasterize

app = typer.Typer(help="Rasterize OpenStreetMap features into GeoTIFF rasters.")
console = Console()


_ENVELOPE_OPTION_KEYS = ("line_width", "width_from_tags")


def _parse_feature(s: str) -> tuple[str, dict, dict] | tuple[str, dict] | dict:
    """Parse a feature string into a tags dict or (name, tags[, options]) tuple.

    Accepted formats:
    - ``'{"building": true}'``          → bare tags dict
    - ``'name:{"building": true}'``     → named tuple
    - ``'name:{"tags": {"highway": true}, "line_width": 8}'`` → envelope with
      per-feature options (``line_width``, ``width_from_tags``)

    A JSON object containing a ``"tags"`` key whose value is an object is
    treated as an envelope; anything else is a plain OSM tag dict.
    """
    brace_idx = s.find("{")
    if brace_idx < 0:
        raise typer.BadParameter(f"Feature string must contain a JSON object: {s!r}")

    prefix = s[:brace_idx]
    json_part = s[brace_idx:]

    try:
        obj = json.loads(json_part)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in feature spec {s!r}: {exc}") from exc

    if not isinstance(obj, dict):
        raise typer.BadParameter(f"Feature JSON must be an object, got: {type(obj).__name__}")

    name = prefix.rstrip(":").strip() if prefix.strip().rstrip(":") else None

    if isinstance(obj.get("tags"), dict):
        tags = obj["tags"]
        options = {k: v for k, v in obj.items() if k != "tags"}
        unknown = set(options) - set(_ENVELOPE_OPTION_KEYS)
        if unknown:
            raise typer.BadParameter(
                f"Unknown option(s) {sorted(unknown)} in feature spec {s!r}; "
                f"valid options are {list(_ENVELOPE_OPTION_KEYS)}"
            )
        if not name:
            raise typer.BadParameter(
                f"Feature specs with options must be named, e.g. 'road:{json_part}'"
            )
        return (name, tags, options)

    if name:
        return (name, obj)
    return obj


@app.command()
def main(
    bbox: Annotated[str, typer.Option("--bbox", "-b", help="Bounding box as 'minx,miny,maxx,maxy' in WGS84.")],
    feature: Annotated[list[str], typer.Option("--feature", "-f", help="OSM feature spec. Format: '{\"key\": val}', 'name:{\"key\": val}', or envelope with line-width options: 'name:{\"tags\": {\"key\": val}, \"line_width\": 8, \"width_from_tags\": true}'. Repeatable.")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output GeoTIFF file path.")],
    resolution: Annotated[float, typer.Option("--resolution", "-r", help="Pixel resolution in metres.")] = 10.0,
    single_layer: Annotated[bool, typer.Option("--single-layer", help="Merge all features into a single band.")] = False,
    fill_nodata: Annotated[bool, typer.Option("--fill-nodata", help="Fill empty pixels with the consensus of neighbouring pixels.")] = False,
    fill_nodata_distance: Annotated[Optional[float], typer.Option("--fill-nodata-distance", help="Max distance in pixels to fill from a labelled pixel. Prevents border flooding. Default: unlimited.")] = None,
    crs: Annotated[Optional[str], typer.Option("--crs", help="Output CRS, e.g. 'EPSG:32632'. Auto-detected if omitted.")] = None,
    date: Annotated[Optional[str], typer.Option("--date", help="Point-in-time ISO 8601 date, e.g. '2020-01-01'. With 'osm', queries OSM as it existed at that date; with 'ohm', selects features existing in the real world at that date (partial dates like '1900' and BCE years like '-0500' work).")] = None,
    provider: Annotated[str, typer.Option("--provider", "-p", help="Data provider: 'osm' (OpenStreetMap) or 'ohm' (OpenHistoricalMap).")] = "osm",
) -> None:
    """Rasterize OSM features for a bounding box into a GeoTIFF."""
    # Parse bbox
    try:
        parts = [float(v.strip()) for v in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        bbox_tuple: tuple[float, float, float, float] = (parts[0], parts[1], parts[2], parts[3])
    except ValueError:
        raise typer.BadParameter(
            f"bbox must be 'minx,miny,maxx,maxy' (4 comma-separated floats), got: {bbox!r}",
            param_hint="--bbox",
        )

    if provider not in ("osm", "ohm"):
        raise typer.BadParameter(
            f"provider must be 'osm' or 'ohm', got: {provider!r}",
            param_hint="--provider",
        )

    # Parse features
    parsed = [_parse_feature(f) for f in feature]

    console.print(f"[bold]Rasterizing {len(parsed)} feature(s)[/bold] → [cyan]{output}[/cyan]")
    date_info = f", date: {date}" if date else ""
    provider_info = f", provider: {provider}" if provider != "osm" else ""
    console.print(f"  bbox: {bbox_tuple}, resolution: {resolution}m, single_layer: {single_layer}, fill_nodata: {fill_nodata}, fill_nodata_distance: {fill_nodata_distance}{date_info}{provider_info}")

    rasterize(
        bbox=bbox_tuple,
        features=parsed,
        resolution=resolution,
        single_layer=single_layer,
        fill_nodata=fill_nodata,
        fill_nodata_distance=fill_nodata_distance,
        output_path=output,
        crs=crs,
        date=date,
        provider=provider,
    )

    console.print(f"[green]Done.[/green] Output written to [cyan]{output}[/cyan]")
