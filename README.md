# osm-rasterizer

Convert OpenStreetMap vector features into GeoTIFF rasters. Define feature classes using OSM tags, specify a bounding box and resolution, and get a multi-band or single-layer categorical raster as output.

## Installation

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/your-org/osm-rasterizer
cd osm-rasterizer
uv sync
```

## Usage

```bash
uv run main.py \
    --bbox "minx,miny,maxx,maxy" \
    --feature 'name:{"osm_key": "value"}' \
    --output output.tif \
    --resolution 10
```

Or using the installed script entry point:

```bash
osm-rasterizer --bbox ... --feature ... --output ...
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

### Output modes

**Multi-band** (default): one `uint8` band per feature, values 0 (absent) or 1 (present).

**Single-layer** (`--single-layer`): one `uint8` band with 1-based category indices (0 = no data). Features listed **later** take priority when areas overlap. Order your features from least to most important.

Band names are stored in the GeoTIFF metadata under the `BAND_NAMES` tag. In single-layer mode, category names are stored under `CATEGORIES`.

## Example: Cambridge land cover

```bash
uv run main.py \
    --bbox "-0.24786388455006128, 52.242894345312415, 0.10397291341351336, 52.34506356709806" \
    --feature 'bare_ground:{"natural": ["bare_rock", "sand", "scree"], "landuse": ["quarry", "brownfield"]}' \
    --feature 'cropland:{"landuse": ["farmland", "orchard", "allotments", "greenhouse_horticulture"]}' \
    --feature 'grassland:{"natural": "grassland", "landuse": ["grass", "meadow", "village_green"], "leisure": "park"}' \
    --feature 'forest:{"landuse": "forest", "natural": "wood"}' \
    --feature 'wetland:{"natural": "wetland"}' \
    --feature 'infrastructure:{"building": true, "landuse": ["industrial", "commercial", "retail", "residential", "construction", "railway"]}' \
    --feature 'road:{"highway": ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "track", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"]}' \
    --feature 'water:{"natural": "water", "waterway": ["river", "canal", "stream", "drain", "ditch"]}' \
    --output cambridge_landcover.tif \
    --resolution 10 \
    --single-layer \
    --fill-nodata \
    --fill-nodata-distance 50
```

This produces a 10 m resolution single-layer categorical raster with 8 land cover classes, with small gaps filled by propagating the nearest label up to 50 pixels away.

## Python API

```python
from osm_rasterizer.rasterize import rasterize

result = rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),  # central London
    features=[
        ("building", {"building": True}),
        ("water", {"natural": "water"}),
        ("park", {"leisure": "park"}),
    ],
    resolution=10.0,
    single_layer=True,
    fill_nodata=True,
    fill_nodata_distance=30,
)

# result.array   — numpy array, shape (1, H, W) in single-layer mode
# result.crs     — rasterio CRS
# result.transform — affine transform
# result.categories — ["building", "water", "park"]

# Or write directly to a file:
rasterize(
    bbox=(-0.15, 51.48, -0.08, 51.52),
    features=[("building", {"building": True})],
    output_path="buildings.tif",
)
```

## How it works

1. **Fetch** — OSM features are downloaded via the Overpass API (using [osmnx](https://osmnx.readthedocs.io/)) and clipped to the exact bounding box.
2. **Project** — The bbox and geometries are reprojected to the best-fit UTM CRS (or a user-specified CRS).
3. **Rasterize** — Each feature class is burned into a `uint8` grid using [rasterio](https://rasterio.readthedocs.io/).
4. **Merge / fill** — Bands are optionally merged into a single categorical layer, and empty pixels optionally filled using a Euclidean distance transform (scipy).
5. **Write** — Output is a cloud-optimised, LZW-compressed, tiled GeoTIFF.

## Development

```bash
# Run tests (unit tests only, no network)
uv run pytest

# Run including integration tests (requires Overpass network access)
uv run pytest -m integration
```
