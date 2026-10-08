"""Sentinel-2 L2A from the Microsoft Planetary Computer, read onto a field grid.

Fixes over v0:
- DN -> reflectance applies the BOA offset (-1000 DN) used from processing
  baseline 04.00 onwards; v0 used raw DN, biasing NDVI towards zero.
- Every date is masked with the Scene Classification Layer (SCL), with cloud
  and shadow masks grown by 20 m because SCL misses cloud edges.
- All matching dates are read, not just the first search result.
- The grid's UTM zone comes from the field itself, never a hardcoded EPSG.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import numpy as np
import planetary_computer
import rasterio
from affine import Affine
from pyproj import CRS
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from scipy import ndimage

log = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
QUANTIFICATION = 10_000
BOA_OFFSET_DN = -1000
OFFSET_FROM_BASELINE = 4.0
OFFSET_FROM_DATE = date(2022, 1, 25)  # first products processed with baseline 04.00

SCL_CLEAR = (4, 5)  # vegetation, not-vegetated (bare soil)
SCL_CLOUD_OR_SHADOW = (3, 8, 9, 10)  # cloud shadow, cloud medium/high, cirrus
CLOUD_BUFFER_PX = 2  # 20 m at 10 m resolution

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="2",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
)


@dataclass(frozen=True)
class Grid:
    crs: CRS
    transform: Affine
    width: int
    height: int

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    @property
    def res(self) -> float:
        return self.transform.a


@dataclass
class Observation:
    """One date of clear-sky-masked surface reflectance on the field grid."""

    date: date
    item_ids: list[str]
    red: np.ndarray  # float32 reflectance, NaN where unusable
    nir: np.ndarray
    scl: np.ndarray  # uint8 scene class, 0 = no data


def grid_for(geom, crs: CRS, res: float = 10.0, pad: float = 30.0) -> Grid:
    """10 m grid snapped to multiples of `res`, which is how Sentinel-2 tiles are aligned."""
    minx, miny, maxx, maxy = geom.bounds
    minx = np.floor((minx - pad) / res) * res
    miny = np.floor((miny - pad) / res) * res
    maxx = np.ceil((maxx + pad) / res) * res
    maxy = np.ceil((maxy + pad) / res) * res
    width, height = int(round((maxx - minx) / res)), int(round((maxy - miny) / res))
    return Grid(CRS(crs), Affine(res, 0, minx, 0, -res, maxy), width, height)


def boa_offset(properties: dict, acquired: date) -> int:
    """BOA_ADD_OFFSET in DN for a scene, from its processing baseline."""
    baseline = properties.get("s2:processing_baseline")
    if baseline is not None:
        return BOA_OFFSET_DN if float(baseline) >= OFFSET_FROM_BASELINE else 0
    log.warning("no processing baseline in metadata; inferring offset from date")
    return BOA_OFFSET_DN if acquired >= OFFSET_FROM_DATE else 0


def to_reflectance(dn: np.ndarray, offset: int) -> np.ndarray:
    """DN -> surface reflectance. DN 0 is no-data."""
    refl = (dn.astype("float32") + offset) / QUANTIFICATION
    refl[dn == 0] = np.nan
    return np.clip(refl, 0.0, None)


def clear_mask(scl: np.ndarray) -> np.ndarray:
    """True where SCL says vegetation or bare soil and no cloud/shadow is within 20 m."""
    cloudy = np.isin(scl, SCL_CLOUD_OR_SHADOW)
    if cloudy.any():
        cloudy = ndimage.binary_dilation(cloudy, iterations=CLOUD_BUFFER_PX)
    return np.isin(scl, SCL_CLEAR) & ~cloudy


def search(geom_wgs84, start: str, end: str, max_tile_cloud: float = 80.0) -> list:
    """All L2A items touching the field. Tile cloud cover is only a loose pre-filter;
    the real decision is made per field from the SCL layer."""
    catalog = Client.open(STAC_URL)
    items = catalog.search(
        collections=[COLLECTION],
        intersects=geom_wgs84.__geo_interface__,
        datetime=f"{start}/{end}",
        query={"eo:cloud_cover": {"lt": max_tile_cloud}},
    ).item_collection()
    return sorted(items, key=lambda it: it.datetime)


def _read_asset(href: str, grid: Grid) -> np.ndarray:
    with rasterio.Env(**GDAL_ENV), rasterio.open(href) as src:
        with WarpedVRT(
            src,
            crs=grid.crs,
            transform=grid.transform,
            width=grid.width,
            height=grid.height,
            resampling=Resampling.nearest,
            src_nodata=0,
            nodata=0,
        ) as vrt:
            return vrt.read(1)


def _read_item(item, grid: Grid):
    signed = planetary_computer.sign(item)
    acquired = item.datetime.date()
    offset = boa_offset(item.properties, acquired)
    red_dn = _read_asset(signed.assets["B04"].href, grid)
    nir_dn = _read_asset(signed.assets["B08"].href, grid)
    scl = _read_asset(signed.assets["SCL"].href, grid).astype("uint8")
    red, nir = to_reflectance(red_dn, offset), to_reflectance(nir_dn, offset)
    keep = clear_mask(scl) & np.isfinite(red) & np.isfinite(nir)
    red[~keep] = np.nan
    nir[~keep] = np.nan
    return item.id, acquired, red, nir, scl


def load_observations(items: list, grid: Grid, workers: int = 6) -> list[Observation]:
    """Read and mask every item; items from the same day (overlapping tiles) are merged."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda it: _read_item(it, grid), items))

    by_day = defaultdict(list)
    for result in results:
        by_day[result[1]].append(result)

    observations = []
    for day in sorted(by_day):
        # Fill gaps from the item with the most clear pixels first.
        parts = sorted(by_day[day], key=lambda r: -np.isfinite(r[2]).sum())
        _, _, red, nir, scl = parts[0]
        red, nir, scl = red.copy(), nir.copy(), scl.copy()
        for _, _, r2, n2, s2 in parts[1:]:
            gap = ~np.isfinite(red) & np.isfinite(r2)
            red[gap], nir[gap], scl[gap] = r2[gap], n2[gap], s2[gap]
            scl_gap = (scl == 0) & (s2 != 0)
            scl[scl_gap] = s2[scl_gap]
        observations.append(Observation(day, [p[0] for p in parts], red, nir, scl))
    return observations
