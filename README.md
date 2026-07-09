# osm-rasterizer

[![PyPI version](https://img.shields.io/pypi/v/osm-rasterizer.svg)](https://pypi.org/project/osm-rasterizer/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/osm-rasterizer.svg)](https://pypi.org/project/osm-rasterizer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Convert OpenStreetMap vector features into GeoTIFF rasters. Define feature classes using OSM tags, specify a bounding box and resolution, and get a multi-band or single-layer categorical raster as output. Also supports [OpenHistoricalMap](https://www.openhistoricalmap.org/) for rasterizing places as they existed at any point in history.

## Installation

```bash
pip install osm-rasterizer
```

Requires Python 3.12+.

## CLI Usage

```bash
osm-rasterizer \
    --bbox "minx,miny,maxx,maxy" \
    --feature 'name:{"osm_key": "value"}' \
    --output output.tif \
    --resolution 10
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--bbox` | `-b` | required | Bounding box as `minx,miny,maxx,maxy` in WGS84 (EPSG:4326) |
| `--feature` | `-f` | required | OSM feature spec (repeatable, see below) |
| `--output` | `-o` | required | Output GeoTIFF path |
| `--resolution` | `-r` | `10.0` | Pixel size in metres |
| `--single-layer` | | `False` | Merge all features into one categorical band |
| `--fill-nodata` | | `False` | Fill empty pixels from nearest labelled neighbour |
| `--fill-nodata-distance` | | unlimited | Max fill distance in pixels (prevents border flooding) |
| `--crs` | | auto | Output CRS, e.g. `EPSG:32630`. Auto-detected as best-fit UTM if omitted |
| `--date` | | current | Point-in-time date in ISO 8601 format (e.g. `2020-01-01`). With `osm`, queries the OSM database as it existed at that date; with `ohm`, selects features that existed in the real world at that date |
| `--provider` | `-p` | `osm` | Data provider: `osm` (OpenStreetMap) or `ohm` (OpenHistoricalMap) |

### Feature spec format

Each `--feature` argument is either a bare JSON tag dict or a named spec:

```
'{"key": value}'                  # unnamed — name inferred from tags
'name:{"key": value}'             # named band/category
```

Tag values follow the [osmnx convention](https://osmnx.readthedocs.io/):

```
'{"building": true}'              # any feature with a "building" tag
'{"highway": "residential"}'      # exact value match
'{"highway": ["primary", "secondary"]}'   # any of these values
```

A named spec may also be an *envelope* — a JSON object with a `"tags"` key plus per-feature options:

```
'road:{"tags": {"highway": true}, "line_width": 8, "width_from_tags": true}'
```

### Line widths

Linestring features (roads, waterways, paths) have no area, so by default they burn as traces exactly **one pixel wide** — a motorway at 2 m resolution becomes a 2 m ribbon. Two per-feature options control this:

- `line_width` (metres) — buffer each line to this real-world width (applied as `width / 2` on each side, in the projected CRS).
- `width_from_tags` (bool) — derive the width per geometry from its own OSM tags: the `width` tag (metres) if present and parseable, else `lanes` × 3.5 m, else the `line_width` fallback (if given), else unbuffered.

Polygons and points are never buffered.

### Output modes

**Multi-band** (default): one `uint8` band per feature, values 0 (absent) or 1 (present).

**Single-layer** (`--single-layer`): one `uint8` band with 1-based category indices (0 = no data). Features listed **later** take priority when areas overlap — order your features from least to most important.

Band names are stored in the GeoTIFF metadata under the `BAND_NAMES` tag. In single-layer mode, category names are stored under `CATEGORIES`.

## Example: Cambridge land cover

```bash
osm-rasterizer \
    --bbox "-0.24786388455006128, 52.242894345312415, 0.10397291341351336, 52.34506356709806" \
    --feature 'bare_ground:{"natural": ["bare_rock", "sand", "scree"], "landuse": ["quarry", "brownfield"]}' \
    --feature 'cropland:{"landuse": ["farmland", "orchard", "allotments", "greenhouse_horticulture"]}' \
    --feature 'grassland:{"natural": "grassland", "landuse": ["grass", "meadow", "village_green"], "leisure": "park"}' \
    --feature 'forest:{"landuse": "forest", "natural": "wood"}' \
    --feature 'wetland:{"natural": "wetland"}' \
    --feature 'infrastructure:{"building": true, "landuse": ["industrial", "commercial", "retail", "residential", "construction", "railway"]}' \
    --feature 'road:{"tags": {"highway": ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "track", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"]}, "line_width": 8, "width_from_tags": true}' \
    --feature 'water:{"natural": "water", "waterway": ["river", "canal", "stream", "drain", "ditch"]}' \
    --output cambridge_landcover.tif \
    --resolution 10 \
    --single-layer \
    --fill-nodata \
    --fill-nodata-distance 50
```

This produces a 10 m resolution single-layer categorical raster with 8 land cover classes, with small gaps filled by propagating the nearest label up to 50 pixels away. Roads are burned at their real-world width where OSM `width`/`lanes` tags exist, falling back to 8 m otherwise.

## Example: Historical data

Use `--date` to extract OSM data as it existed at a specific point in time:

```bash
osm-rasterizer \
    --bbox "-0.13,51.49,-0.11,51.51" \
    --feature 'building:{"building": true}' \
    --output london_buildings_2015.tif \
    --date "2015-01-01"
```

## Example: OpenHistoricalMap

The `--date` option on the default `osm` provider is limited to the history of the OSM *database* (2004 onwards). To rasterize old places — cities as they were in 1900, ancient road networks, vanished buildings — use the `ohm` provider, which fetches from [OpenHistoricalMap](https://www.openhistoricalmap.org/)'s Overpass API:

```bash
osm-rasterizer \
    --bbox "-0.13,51.49,-0.11,51.51" \
    --feature 'building:{"building": true}' \
    --output london_buildings_1900.tif \
    --provider ohm \
    --date "1900-01-01"
```

Notes:

- OHM uses the same tag vocabulary as OSM, so feature specs work unchanged. Data coverage depends on what has been mapped in OHM for your area.
- OHM features carry `start_date`/`end_date` tags describing when they existed in the real world; `--date` keeps a feature when `start_date <= date <= end_date`. Features missing a `start_date` (or `end_date`) are treated as always existing (or still existing), and unparseable dates never exclude a feature.
- Dates may be partial (`1900`, `1900-06`) or BCE (`-0500` for 500 BCE).
- Without `--date`, all OHM features of all eras are rasterized together.
- OHM data is CC0-licensed.

## Python API

```python
from osm_rasterizer import rasterize

result = rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),  # central London
    features=[
        ("building", {"building": True}),
        ("water", {"natural": "water"}),
        ("park", {"leisure": "park"}),
        # linestrings: burn roads at their OSM-tagged width, else 8 m wide
        ("road", {"highway": True}, {"line_width": 8.0, "width_from_tags": True}),
    ],
    resolution=10.0,
    single_layer=True,
    fill_nodata=True,
    fill_nodata_distance=30,
)

# result.array      — numpy array, shape (1, H, W) in single-layer mode
# result.crs        — rasterio CRS
# result.transform  — affine transform
# result.categories — ["building", "water", "park", "road"]

# Write directly to a file:
rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),
    features=[("building", {"building": True})],
    output_path="buildings.tif",
)

# Historical query:
rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),
    features=[("building", {"building": True})],
    output_path="buildings_2018.tif",
    date="2018-06-01",
)

# OpenHistoricalMap query:
rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),
    features=[("building", {"building": True})],
    output_path="buildings_1900.tif",
    provider="ohm",
    date="1900-01-01",
)
```

## How it works

1. **Fetch** — Features are downloaded via the Overpass API (using [osmnx](https://osmnx.readthedocs.io/)) from OpenStreetMap or OpenHistoricalMap and clipped to the exact bounding box. An optional `date` parameter queries the historical state of the map (OSM: Overpass `[date:]` attic query; OHM: filtering by `start_date`/`end_date` tags).
2. **Project** — The bbox and geometries are reprojected to the best-fit UTM CRS (or a user-specified CRS).
3. **Rasterize** — Each feature class is burned into a `uint8` grid using [rasterio](https://rasterio.readthedocs.io/). Linestrings are optionally buffered to a real-world width (from the `line_width` option or the features' own `width`/`lanes` tags) before burning; otherwise they render one pixel wide.
4. **Merge / fill** — Bands are optionally merged into a single categorical layer, and empty pixels optionally filled using a Euclidean distance transform (scipy).
5. **Write** — Output is a cloud-optimised, LZW-compressed, tiled GeoTIFF.

## Development

```bash
git clone https://github.com/ancazugo/osm-rasterizer
cd osm-rasterizer
uv sync

# Run tests (unit tests only, no network)
uv run pytest

# Run including integration tests (requires Overpass network access)
uv run pytest -m integration
```
