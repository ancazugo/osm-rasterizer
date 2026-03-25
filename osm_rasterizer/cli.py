from __future__ import annotations

import json
from typing import Annotated, Optional

import typer
from rich.console import Console

from .rasterize import rasterize

app = typer.Typer(help="Rasterize OpenStreetMap features into GeoTIFF rasters.")
console = Console()


def _parse_feature(s: str) -> tuple[str, dict] | dict:
    """Parse a feature string into a (name, tags) tuple or bare tags dict.

    Accepted formats:
    - ``'{"building": true}'``          → bare dict
    - ``'name:{"building": true}'``     → named tuple
    """
    brace_idx = s.find("{")
    if brace_idx < 0:
        raise typer.BadParameter(f"Feature string must contain a JSON object: {s!r}")

    prefix = s[:brace_idx]
    json_part = s[brace_idx:]

    try:
        tags = json.loads(json_part)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in feature spec {s!r}: {exc}") from exc

    if not isinstance(tags, dict):
        raise typer.BadParameter(f"Feature JSON must be an object, got: {type(tags).__name__}")

    name = prefix.rstrip(":").strip() if prefix.strip().rstrip(":") else None

    if name:
        return (name, tags)
    return tags


@app.command()
def main(
    bbox: Annotated[str, typer.Option("--bbox", "-b", help="Bounding box as 'minx,miny,maxx,maxy' in WGS84.")],
    feature: Annotated[list[str], typer.Option("--feature", "-f", help="OSM feature spec. Format: '{\"key\": val}' or 'name:{\"key\": val}'. Repeatable.")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output GeoTIFF file path.")],
    resolution: Annotated[float, typer.Option("--resolution", "-r", help="Pixel resolution in metres.")] = 10.0,
    single_layer: Annotated[bool, typer.Option("--single-layer", help="Merge all features into a single band.")] = False,
    fill_nodata: Annotated[bool, typer.Option("--fill-nodata", help="Fill empty pixels with the consensus of neighbouring pixels.")] = False,
    fill_nodata_distance: Annotated[Optional[float], typer.Option("--fill-nodata-distance", help="Max distance in pixels to fill from a labelled pixel. Prevents border flooding. Default: unlimited.")] = None,
    crs: Annotated[Optional[str], typer.Option("--crs", help="Output CRS, e.g. 'EPSG:32632'. Auto-detected if omitted.")] = None,
    date: Annotated[Optional[str], typer.Option("--date", help="Point-in-time ISO 8601 date, e.g. '2020-01-01'. Queries OSM as it existed at that date.")] = None,
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

    # Parse features
    parsed = [_parse_feature(f) for f in feature]

    console.print(f"[bold]Rasterizing {len(parsed)} feature(s)[/bold] → [cyan]{output}[/cyan]")
    date_info = f", date: {date}" if date else ""
    console.print(f"  bbox: {bbox_tuple}, resolution: {resolution}m, single_layer: {single_layer}, fill_nodata: {fill_nodata}, fill_nodata_distance: {fill_nodata_distance}{date_info}")

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
    )

    console.print(f"[green]Done.[/green] Output written to [cyan]{output}[/cyan]")
