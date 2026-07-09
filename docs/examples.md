# Examples

## Cambridge land cover

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

## Historical data

Use `--date` to extract OSM data as it existed at a specific point in time:

```bash
osm-rasterizer \
    --bbox "-0.13,51.49,-0.11,51.51" \
    --feature 'building:{"building": true}' \
    --output london_buildings_2015.tif \
    --date "2015-01-01"
```

## OpenHistoricalMap

The `--date` option on the default `osm` provider is limited to the history of the OSM *database* (2004 onwards). To rasterize old places — cities as they were in 1900, ancient road networks, vanished buildings — use the `ohm` provider, which fetches from [OpenHistoricalMap](https://www.openhistoricalmap.org/)'s Overpass API:

```bash
osm-rasterizer \
    --bbox "-0.13,51.49,-0.11,51.51" \
    --feature 'building:{"building": true}' \
    --output london_buildings_1900.tif \
    --provider ohm \
    --date "1900-01-01"
```

!!! note

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

See the [Python API](api.md) reference for full signatures.
