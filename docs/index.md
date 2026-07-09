# osm-rasterizer

![osm-rasterizer logo](assets/logos/osm-rasterizer-mark.svg#only-light){ width="160" }
![osm-rasterizer logo](assets/logos/osm-rasterizer-mark-dark.svg#only-dark){ width="160" }

[![PyPI version](https://img.shields.io/pypi/v/osm-rasterizer.svg)](https://pypi.org/project/osm-rasterizer/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/osm-rasterizer.svg)](https://pypi.org/project/osm-rasterizer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Convert OpenStreetMap vector features into GeoTIFF rasters. Define feature classes using OSM tags, specify a bounding box and resolution, and get a multi-band or single-layer categorical raster as output. Also supports [OpenHistoricalMap](https://www.openhistoricalmap.org/) for rasterizing places as they existed at any point in history.

## Quick start

```bash
pip install osm-rasterizer

osm-rasterizer \
    --bbox "minx,miny,maxx,maxy" \
    --feature 'name:{"osm_key": "value"}' \
    --output output.tif \
    --resolution 10
```

Or from Python:

```python
from osm_rasterizer import rasterize

result = rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),  # central London
    features=[
        ("building", {"building": True}),
        ("water", {"natural": "water"}),
    ],
    resolution=10.0,
)
```

See [Installation](installation.md), [CLI Usage](cli.md), [Examples](examples.md), and the [Python API](api.md) reference.

## How it works

1. **Fetch** — Features are downloaded via the Overpass API (using [osmnx](https://osmnx.readthedocs.io/)) from OpenStreetMap or OpenHistoricalMap and clipped to the exact bounding box. An optional `date` parameter queries the historical state of the map (OSM: Overpass `[date:]` attic query; OHM: filtering by `start_date`/`end_date` tags).
2. **Project** — The bbox and geometries are reprojected to the best-fit UTM CRS (or a user-specified CRS).
3. **Rasterize** — Each feature class is burned into a `uint8` grid using [rasterio](https://rasterio.readthedocs.io/). Linestrings are optionally buffered to a real-world width (from the `line_width` option or the features' own `width`/`lanes` tags) before burning; otherwise they render one pixel wide.
4. **Merge / fill** — Bands are optionally merged into a single categorical layer, and empty pixels optionally filled using a Euclidean distance transform (scipy).
5. **Write** — Output is a cloud-optimised, LZW-compressed, tiled GeoTIFF.

## License

MIT. OpenStreetMap data is © OpenStreetMap contributors (ODbL); OpenHistoricalMap data is CC0.
