from __future__ import annotations

import dataclasses
import warnings
from math import ceil
from pathlib import Path
from typing import Union

import geopandas as gpd
import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize as rio_rasterize

from .crs import get_utm_crs
from .fetch import fetch_features

OsmTags = dict[str, Union[str, bool, list[str]]]
FeatureOptions = dict[str, Union[float, bool]]
FeatureSpec = Union[OsmTags, tuple[str, OsmTags], tuple[str, OsmTags, FeatureOptions]]

# Assumed width of a single traffic lane, used when deriving a line width
# from a `lanes` tag.
LANE_WIDTH_M = 3.5

VALID_FEATURE_OPTIONS = ("line_width", "width_from_tags")


@dataclasses.dataclass
class RasterizeResult:
    """Result of a rasterization operation.

    When ``single_layer=False`` (default): ``array`` shape is ``(n_bands, H, W)``,
    values are 0/1 per-feature presence masks.

    When ``single_layer=True``: ``array`` shape is ``(1, H, W)``, values are
    1-based category indices into ``categories`` (0 = no data).  The priority
    order is determined by the feature list order passed to ``rasterize()``:
    the **last** feature has the highest priority and wins conflicts.
    """

    array: np.ndarray      # shape: (n_bands, height, width), dtype uint8
    transform: Affine
    crs: rasterio.CRS
    band_names: list[str]
    nodata: int = 0
    categories: list[str] | None = None  # populated in single_layer mode


def _fill_nodata_consensus(
    arr: np.ndarray,
    max_distance: float | None = None,
) -> np.ndarray:
    """Fill zero pixels with the value of their nearest non-zero neighbour.

    Uses a Euclidean distance transform to propagate labels outward from all
    labelled pixels simultaneously in a single O(n) pass.

    Parameters
    ----------
    arr:
        2-D ``uint8`` array.
    max_distance:
        Maximum distance in pixels within which a zero pixel will be filled.
        Zero pixels farther than this from any labelled pixel are left as 0,
        preventing border areas outside OSM coverage from being flooded.
        ``None`` (default) fills all zero pixels regardless of distance.
    """
    from scipy.ndimage import distance_transform_edt

    zero_mask = arr == 0
    if not zero_mask.any() or arr.max() == 0:
        return arr.copy()

    distances, nearest = distance_transform_edt(zero_mask, return_indices=True)

    if max_distance is not None:
        fill_mask = zero_mask & (distances <= max_distance)
    else:
        fill_mask = zero_mask

    result = arr.copy()
    result[fill_mask] = arr[nearest[0][fill_mask], nearest[1][fill_mask]]
    return result


def _auto_name(tags: dict, index: int) -> str:
    """Generate a band name from an OSM tag dict."""
    if not tags:
        return f"feature_{index}"
    key = next(iter(tags))
    val = tags[key]
    if isinstance(val, bool) or val is True:
        return key
    if isinstance(val, str):
        return f"{key}_{val}"
    return key


def _validate_options(options: dict, context: str) -> dict:
    """Validate a feature options dict, returning it unchanged."""
    if not isinstance(options, dict):
        raise TypeError(f"feature options for {context} must be a dict, got {type(options).__name__}")
    unknown = set(options) - set(VALID_FEATURE_OPTIONS)
    if unknown:
        raise ValueError(
            f"unknown feature option(s) {sorted(unknown)} for {context}; "
            f"valid options are {list(VALID_FEATURE_OPTIONS)}"
        )
    return options


def _normalize_features(
    features: list,
) -> list[tuple[str, dict, dict]]:
    """Normalize feature specs to ``[(name, tags, options), ...]``."""
    if not features:
        raise ValueError("features list must not be empty")

    # Determine whether all are named tuples or all are bare dicts
    are_tuples = [isinstance(f, tuple) for f in features]
    if any(are_tuples) and not all(are_tuples):
        raise TypeError(
            "features must be either all bare dicts or all (name, dict) tuples, "
            "not a mix of both"
        )

    normalized: list[tuple[str, dict, dict]] = []
    for i, f in enumerate(features):
        if isinstance(f, tuple):
            if len(f) == 2:
                name, tags = f
                options: dict = {}
            elif len(f) == 3:
                name, tags, options = f
            else:
                raise TypeError(
                    f"feature tuples must be (name, tags) or (name, tags, options), "
                    f"got tuple of length {len(f)}"
                )
            normalized.append((str(name), tags, _validate_options(options, f"feature '{name}'")))
        else:
            normalized.append((_auto_name(f, i), f, {}))
    return normalized


def _parse_width_tag(value) -> Union[float, None]:
    """Leniently parse an OSM ``width`` tag value in metres.

    Handles plain numbers (``"12"``, ``"12.5"``, ``12.5``) and an optional
    metre suffix (``"12 m"``, ``"12m"``).  Returns None for anything else
    (missing values, imperial notation, ranges, junk).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        width = float(value)
        return width if width == width and width > 0 else None  # NaN/non-positive → None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.endswith("m") and not text.endswith("nm") and not text.endswith("km"):
        text = text[:-1].strip()
    try:
        width = float(text)
    except ValueError:
        return None
    return width if width > 0 else None


def _row_line_width(width_tag, lanes_tag, options: dict) -> Union[float, None]:
    """Resolve the burn width in metres for one geometry.

    Order: ``width`` tag → ``lanes`` tag × LANE_WIDTH_M → ``line_width``
    option → None (unbuffered).  Tags are consulted only when the
    ``width_from_tags`` option is set.
    """
    if options.get("width_from_tags"):
        width = _parse_width_tag(width_tag)
        if width is not None:
            return width
        lanes = _parse_width_tag(lanes_tag)
        if lanes is not None:
            return lanes * LANE_WIDTH_M
    line_width = options.get("line_width")
    if line_width is not None:
        return float(line_width)
    return None


def _apply_line_widths(gdf_utm, options: dict):
    """Buffer line geometries to their resolved width (in CRS units, metres).

    Returns a GeoSeries of geometries with LineString/MultiLineString rows
    buffered by ``width / 2``; other geometry types and lines with no
    resolvable width pass through unchanged.  No-op (returns the original
    geometry column) when the options request no widths.
    """
    if not options.get("line_width") and not options.get("width_from_tags"):
        return gdf_utm.geometry

    width_col = gdf_utm["width"] if "width" in gdf_utm.columns else [None] * len(gdf_utm)
    lanes_col = gdf_utm["lanes"] if "lanes" in gdf_utm.columns else [None] * len(gdf_utm)

    buffered = []
    for geom, width_tag, lanes_tag in zip(gdf_utm.geometry, width_col, lanes_col):
        if geom is not None and geom.geom_type in ("LineString", "MultiLineString"):
            width = _row_line_width(width_tag, lanes_tag, options)
            if width is not None:
                geom = geom.buffer(width / 2.0)
        buffered.append(geom)
    return gpd.GeoSeries(buffered, crs=gdf_utm.crs)


def rasterize(
    bbox: tuple[float, float, float, float],
    features: list,
    resolution: float = 10.0,
    single_layer: bool = False,
    fill_nodata: bool = False,
    fill_nodata_distance: Union[float, None] = None,
    output_path: Union[str, Path, None] = None,
    transform: Union[Affine, None] = None,
    crs: Union[rasterio.CRS, str, None] = None,
    date: Union[str, None] = None,
    provider: str = "osm",
) -> Union[RasterizeResult, None]:
    """Rasterize OSM features into a GeoTIFF or return a RasterizeResult.

    Parameters
    ----------
    bbox:
        ``(minx, miny, maxx, maxy)`` in WGS84 degrees.
    features:
        List of OSM tag dicts, ``(name, tags)`` tuples, or
        ``(name, tags, options)`` tuples.  The options dict controls how
        linestring geometries (roads, waterways, …) are burned:

        - ``line_width`` (float): real-world width in metres; lines are
          buffered by ``line_width / 2`` in the projected CRS before
          rasterization.
        - ``width_from_tags`` (bool): derive a per-geometry width from the
          feature's own OSM tags — ``width`` in metres, else ``lanes`` ×
          3.5 m — falling back to ``line_width`` (if given) when neither
          tag is present or parseable.

        Without options, lines burn as 1-pixel-wide traces.  Polygons and
        points are never buffered.
    resolution:
        Pixel size in metres (ignored when *transform* is supplied).
    single_layer:
        If True, merge all features into a single categorical band.  Pixel
        values are 1-based indices into the feature list (0 = no data).
        Conflicts are resolved by priority: features listed **later** win.
        Reorder your feature list from least to most important category.
    fill_nodata:
        If True, replace empty (zero) pixels with the value of their nearest
        non-zero neighbour.  Applied per-band in multi-band mode and on the
        merged array in single-layer mode.
    fill_nodata_distance:
        Maximum distance in pixels within which an empty pixel will be
        filled.  Pixels farther than this from any labelled pixel are left
        as 0, preventing border areas outside OSM coverage from being
        flooded with a nearby label.  Ignored when *fill_nodata* is False.
        ``None`` (default) fills all empty pixels regardless of distance.
    output_path:
        Write a GeoTIFF here; return None instead of RasterizeResult.
    transform:
        Explicit affine transform (overrides *resolution*).
    crs:
        Output CRS; auto-detected from *bbox* if None.
    date:
        Optional ISO 8601 date string (e.g. ``"2020-01-01"``).  With
        ``provider="osm"`` this queries OSM data as it existed at that point
        in time; with ``provider="ohm"`` it selects features that existed in
        the real world at that date via their ``start_date``/``end_date``
        tags (partial dates like ``"1900"`` and BCE years like ``"-0500"``
        are supported).
    provider:
        Data provider: ``"osm"`` (OpenStreetMap, default) or ``"ohm"``
        (OpenHistoricalMap, CC0-licensed historical data).

    Returns
    -------
    RasterizeResult or None
        None when *output_path* is given; RasterizeResult otherwise.
    """
    # 1. Validate
    minx, miny, maxx, maxy = bbox
    if minx >= maxx or miny >= maxy:
        raise ValueError(
            f"Invalid bbox {bbox}: minx must be < maxx and miny must be < maxy"
        )
    if not features:
        raise ValueError("features list must not be empty")

    # 2. Normalize features
    named_features = _normalize_features(features)

    # 3. Determine output CRS
    if crs is None:
        out_crs_pyproj = get_utm_crs(bbox)
        out_crs = rasterio.CRS.from_wkt(out_crs_pyproj.to_wkt())
    elif isinstance(crs, str):
        out_crs = rasterio.CRS.from_string(crs)
    else:
        out_crs = crs

    # 4. Reproject bbox corners to UTM
    transformer = Transformer.from_crs("EPSG:4326", out_crs.to_wkt(), always_xy=True)
    corners_x, corners_y = transformer.transform(
        [minx, maxx, minx, maxx],
        [miny, miny, maxy, maxy],
    )
    utm_minx = min(corners_x)
    utm_maxx = max(corners_x)
    utm_miny = min(corners_y)
    utm_maxy = max(corners_y)

    # 5. Compute affine transform and grid size
    if transform is None:
        out_transform = Affine.translation(utm_minx, utm_maxy) * Affine.scale(resolution, -resolution)
        width = ceil((utm_maxx - utm_minx) / resolution)
        height = ceil((utm_maxy - utm_miny) / resolution)
    else:
        out_transform = transform
        px_width = abs(transform.a)
        px_height = abs(transform.e)
        width = ceil((utm_maxx - utm_minx) / px_width)
        height = ceil((utm_maxy - utm_miny) / px_height)

    # 6. Per-feature rasterization
    bands: list[np.ndarray] = []
    band_names: list[str] = []

    for name, tags, options in named_features:
        gdf = fetch_features(bbox, tags, date=date, provider=provider)

        if gdf.empty:
            warnings.warn(
                f"No features found for tag spec {tags!r} (band '{name}'); "
                "writing zero band.",
                stacklevel=2,
            )
            bands.append(np.zeros((height, width), dtype=np.uint8))
            band_names.append(name)
            continue

        gdf_utm = gdf.to_crs(out_crs.to_wkt())
        geometries = _apply_line_widths(gdf_utm, options)

        shapes = (
            (geom, 1)
            for geom in geometries
            if geom is not None and not geom.is_empty
        )
        burned = rio_rasterize(
            shapes=shapes,
            out_shape=(height, width),
            transform=out_transform,
            fill=0,
            dtype=np.uint8,
        )
        bands.append(burned)
        band_names.append(name)

    # 7. Handle single_layer
    if single_layer:
        # Priority-based merge: later features overwrite earlier ones.
        # Pixel value = 1-based category index; 0 = no data.
        merged = np.zeros((height, width), dtype=np.uint8)
        for i, band in enumerate(bands):
            merged = np.where(band > 0, np.uint8(i + 1), merged)
        if fill_nodata:
            merged = _fill_nodata_consensus(merged, max_distance=fill_nodata_distance)
        array = merged[np.newaxis, ...]
        final_band_names = ["landcover"]
        categories = band_names
    else:
        if fill_nodata:
            bands = [_fill_nodata_consensus(b, max_distance=fill_nodata_distance) for b in bands]
        array = np.stack(bands, axis=0)
        final_band_names = band_names
        categories = None

    result = RasterizeResult(
        array=array,
        transform=out_transform,
        crs=out_crs,
        band_names=final_band_names,
        categories=categories,
    )

    # 8. Write or return
    if output_path is None:
        return result

    output_path = Path(output_path)
    n_bands, h, w = array.shape
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=n_bands,
        dtype=np.uint8,
        crs=out_crs,
        transform=out_transform,
        nodata=0,
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(array)
        dst.update_tags(BAND_NAMES=",".join(final_band_names))
        if categories is not None:
            # single_layer mode: record the category→value mapping.
            # Value 1 = categories[0], value 2 = categories[1], etc.
            dst.update_tags(CATEGORIES=",".join(categories))
        for i, band_name in enumerate(final_band_names, start=1):
            dst.update_tags(i, name=band_name)

    return None
