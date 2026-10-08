"""Turn the tier raster into scouting-zone polygons with per-zone statistics.

Zone statistics are read from the same pixel grid the polygons come from
(via a label array), so there is no polygon-vs-raster CRS mismatch to get
wrong. In v0 that mismatch silently made every zone "Unknown".
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize, shapes
from scipy import ndimage
from shapely.geometry import shape

from .anomaly import NODATA, NORMAL, SCOUT_FIRST, TIER_LABELS, TIER_NAMES, UNUSUAL_PATTERN, WATCH, Season
from .sentinel import Grid

FOUR_CONNECTED = ndimage.generate_binary_structure(2, 1)
# A zone this large a share of its crop unit is more likely a management difference
# (sown later, other variety, different previous crop) than a local problem.
LARGE_SHARE_OF_UNIT = 0.20


def _components(mask: np.ndarray):
    labels, n = ndimage.label(mask, structure=FOUR_CONNECTED)
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    return labels, sizes


def clean_tiers(tiers: np.ndarray, min_pixels: int) -> np.ndarray:
    """Drop zones smaller than the minimum mapping unit.

    Small flagged patches become Normal; small Scout-first islands inside a
    large enough Watch zone are kept as Watch; small Watch fragments on the rim
    of a Scout-first zone join it; small Unusual patches are dropped.
    """
    out = tiers.copy()
    labels, sizes = _components(np.isin(out, (WATCH, SCOUT_FIRST)))
    small = (sizes < min_pixels)[labels] & (labels > 0)
    out[small] = NORMAL

    labels, sizes = _components(out == SCOUT_FIRST)
    small = (sizes < min_pixels)[labels] & (labels > 0)
    out[small] = WATCH

    labels, sizes = _components(out == WATCH)
    if labels.max():
        near_scout = ndimage.binary_dilation(out == SCOUT_FIRST, structure=FOUR_CONNECTED)
        touches = np.zeros(labels.max() + 1, dtype=bool)
        touches[1:] = ndimage.maximum(near_scout, labels, index=np.arange(1, labels.max() + 1)).astype(bool)
        small = (sizes < min_pixels)[labels] & (labels > 0)
        out[small & touches[labels]] = SCOUT_FIRST
        out[small & ~touches[labels]] = NORMAL

    labels, sizes = _components(out == UNUSUAL_PATTERN)
    small = (sizes < min_pixels)[labels] & (labels > 0)
    out[small] = NODATA
    return out


def zones_from_tiers(tiers: np.ndarray, season: Season, grid: Grid, units: np.ndarray,
                     usable_by_unit: dict[int, int], field_utm=None, edge_m: float = 0.0) -> gpd.GeoDataFrame:
    """One polygon per connected Scout-first / Watch / Unusual region, in EPSG:4326.

    `at_field_edge` marks zones within about a pixel of the analysed edge: headland
    compaction, hedge shading and overlaps at turning are common causes there.
    """
    pixel_ha = grid.res**2 / 1e4
    records, zone_id = [], 0
    for tier in (SCOUT_FIRST, WATCH, UNUSUAL_PATTERN):
        labels, _ = _components(tiers == tier)
        if labels.max() == 0:
            continue
        geoms = {}
        for geom, value in shapes(labels.astype("int32"), mask=labels > 0, transform=grid.transform):
            geoms.setdefault(int(value), []).append(shape(geom))
        for label, parts in geoms.items():
            px = labels == label
            zone_id += 1
            n_valid = season.n_valid[px]
            unit = int(np.bincount(units[px]).argmax())
            geom = parts[0] if len(parts) == 1 else gpd.GeoSeries(parts).union_all()
            scored = tier != UNUSUAL_PATTERN
            records.append(
                dict(
                    zone_id=zone_id,
                    unit_id=unit if scored else None,
                    tier=TIER_NAMES[tier],
                    label=TIER_LABELS[tier],
                    area_ha=round(float(px.sum() * pixel_ha), 2),
                    persistence_pct=round(float(np.nanmean(season.persistence[px]) * 100), 1) if scored else None,
                    flagged_dates=(f"{int(np.median(season.n_flagged[px]))} of {int(np.median(n_valid))}"
                                   if scored else None),
                    ndvi_deficit_pct=round(float(np.nanmean(season.mean_relative[px]) * 100), 1) if scored else None,
                    median_ndvi=round(float(np.nanmean(season.median_ndvi[px])), 3) if scored else None,
                    usable_dates_in_season=usable_by_unit.get(unit, 0) if scored else None,
                    at_field_edge=bool(field_utm is not None
                                       and geom.distance(field_utm.boundary) <= edge_m + 1.5 * grid.res),
                    share_of_unit_pct=round(float(px.sum() / max((units == unit).sum(), 1) * 100), 1) if scored else None,
                    likely_management_difference=bool(scored and px.sum() >= LARGE_SHARE_OF_UNIT * (units == unit).sum()
                                                      and px.sum() * pixel_ha >= 1.0),
                    geometry=geom,
                )
            )

    columns = [
        "zone_id", "unit_id", "tier", "label", "area_ha", "persistence_pct", "flagged_dates",
        "ndvi_deficit_pct", "median_ndvi", "usable_dates_in_season", "at_field_edge",
        "share_of_unit_pct", "likely_management_difference", "geometry",
    ]
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=4326)
    gdf = gpd.GeoDataFrame(records, columns=columns, geometry="geometry", crs=grid.crs)
    return gdf.to_crs(4326)


def zone_series(zones: gpd.GeoDataFrame, grid: Grid, unit_dates: dict) -> dict:
    """Per scored zone and usable date: the zone's median NDVI, the rest of its crop unit, and
    whether the zone was flagged that date (at least half of its pixels). This is the evidence
    behind "weaker on 8 of 10 clear dates" – shown to the user as a chart, not hidden."""
    out: dict = {}
    if not len(zones):
        return out
    local = zones.to_crs(grid.crs)
    for _, z in local.iterrows():
        if z.unit_id is None or pd.isna(z.unit_id) or int(z.unit_id) not in unit_dates:
            continue  # unusual-pattern zones are not compared with any crop
        umask, dates = unit_dates[int(z.unit_id)]
        zmask = rasterize([z.geometry], out_shape=grid.shape, transform=grid.transform, fill=0,
                          default_value=1).astype(bool) & umask
        if not zmask.any():
            continue
        rest = umask & ~zmask
        rows = []
        for d, v, a in dates:
            zv, rv = v[zmask], v[rest]
            zv, rv = zv[np.isfinite(zv)], rv[np.isfinite(rv)]
            valid = a.valid[zmask]
            share = float(a.flagged[zmask][valid].mean()) if valid.any() else 0.0
            rows.append(dict(date=d, zone=round(float(np.median(zv)), 3) if zv.size else None,
                             crop=round(float(np.median(rv)), 3) if rv.size else None, flagged=share >= 0.5))
        out[str(int(z.zone_id))] = dict(unit_id=int(z.unit_id), dates=rows)
    return out
