# CLI Usage

```bash
osm-rasterizer \
    --bbox "minx,miny,maxx,maxy" \
    --feature 'name:{"osm_key": "value"}' \
    --output output.tif \
    --resolution 10
```

## Options

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

## Feature spec format

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

## Line widths

Linestring features (roads, waterways, paths) have no area, so by default they burn as traces exactly **one pixel wide** — a motorway at 2 m resolution becomes a 2 m ribbon. Two per-feature options control this:

- `line_width` (metres) — buffer each line to this real-world width (applied as `width / 2` on each side, in the projected CRS).
- `width_from_tags` (bool) — derive the width per geometry from its own OSM tags: the `width` tag (metres) if present and parseable, else `lanes` × 3.5 m, else the `line_width` fallback (if given), else unbuffered.

Polygons and points are never buffered.

## Output modes

**Multi-band** (default): one `uint8` band per feature, values 0 (absent) or 1 (present).

**Single-layer** (`--single-layer`): one `uint8` band with 1-based category indices (0 = no data). Features listed **later** take priority when areas overlap — order your features from least to most important.

Band names are stored in the GeoTIFF metadata under the `BAND_NAMES` tag. In single-layer mode, category names are stored under `CATEGORIES`.
