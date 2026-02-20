from __future__ import annotations

import dataclasses
import warnings
from math import ceil
from pathlib import Path
from typing import Union

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize as rio_rasterize

from .crs import get_utm_crs
from .fetch import fetch_features

OsmTags = dict[str, Union[str, bool, list[str]]]
FeatureSpec = Union[OsmTags, tuple[str, OsmTags]]


@dataclasses.dataclass
class RasterizeResult:
    """Result of a rasterization operation."""

    array: np.ndarray      # shape: (n_bands, height, width), dtype uint8
    transform: Affine
    crs: rasterio.CRS
    band_names: list[str]
    nodata: int = 0


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


def _normalize_features(
    features: list,
) -> list[tuple[str, dict]]:
    """Normalize feature specs to ``[(name, tags), ...]``."""
    if not features:
        raise ValueError("features list must not be empty")

    # Determine whether all are named tuples or all are bare dicts
    are_tuples = [isinstance(f, tuple) for f in features]
    if any(are_tuples) and not all(are_tuples):
        raise TypeError(
            "features must be either all bare dicts or all (name, dict) tuples, "
            "not a mix of both"
        )

    normalized: list[tuple[str, dict]] = []
    for i, f in enumerate(features):
        if isinstance(f, tuple):
            name, tags = f
            normalized.append((str(name), tags))
        else:
            normalized.append((_auto_name(f, i), f))
    return normalized


def rasterize(
    bbox: tuple[float, float, float, float],
    features: list,
    resolution: float = 10.0,
    single_layer: bool = False,
    output_path: Union[str, Path, None] = None,
    transform: Union[Affine, None] = None,
    crs: Union[rasterio.CRS, str, None] = None,
) -> Union[RasterizeResult, None]:
    """Rasterize OSM features into a GeoTIFF or return a RasterizeResult.

    Parameters
    ----------
    bbox:
        ``(minx, miny, maxx, maxy)`` in WGS84 degrees.
    features:
        List of OSM tag dicts or ``(name, tags)`` tuples.
    resolution:
        Pixel size in metres (ignored when *transform* is supplied).
    single_layer:
        If True, merge all feature bands into one.
    output_path:
        Write a GeoTIFF here; return None instead of RasterizeResult.
    transform:
        Explicit affine transform (overrides *resolution*).
    crs:
        Output CRS; auto-detected from *bbox* if None.

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

    for name, tags in named_features:
        gdf = fetch_features(bbox, tags)

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

        shapes = (
            (geom, 1)
            for geom in gdf_utm.geometry
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
    stacked = np.stack(bands, axis=0)
    if single_layer:
        array = np.any(stacked, axis=0, keepdims=True).astype(np.uint8)
        final_band_names = ["merged"]
    else:
        array = stacked
        final_band_names = band_names

    result = RasterizeResult(
        array=array,
        transform=out_transform,
        crs=out_crs,
        band_names=final_band_names,
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
        for i, band_name in enumerate(final_band_names, start=1):
            dst.update_tags(i, name=band_name)

    return None
