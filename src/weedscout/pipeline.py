"""Boundary in -> scouting map out, for one field."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import numpy as np
from rasterio.features import rasterize

from . import __version__
from .anomaly import (
    NODATA, NORMAL, SCOUT_FIRST, TIER_LABELS, UNUSUAL_PATTERN, WATCH, Season, Settings, date_anomaly, ndvi,
    season_summary,
)
from .boundary import Field
from .export import quicklook, write_cog, write_report, write_vectors
from .sentinel import Grid, Observation, grid_for, load_observations, search
from .units import UNUSUAL, UnitSettings, crop_units, interior, real_units
from .zones import clean_tiers, zones_from_tiers

log = logging.getLogger(__name__)


def field_mask(field: Field, grid: Grid, edge_buffer_m: float) -> np.ndarray:
    """Pixels whose centre lies inside the field shrunk by `edge_buffer_m`."""
    inner = field.geometry.buffer(-edge_buffer_m) if edge_buffer_m > 0 else field.geometry
    if inner.is_empty:
        return np.zeros(grid.shape, dtype=bool)
    return rasterize([inner], out_shape=grid.shape, transform=grid.transform, fill=0, default_value=1).astype(bool)


def _clear_fraction(v: np.ndarray, mask: np.ndarray) -> float:
    return float((mask & np.isfinite(v)).sum() / mask.sum()) if mask.any() else 0.0


def select_dates(ndvis: list[tuple[Observation, np.ndarray]], mask: np.ndarray, s: Settings):
    """Decide which dates can be used for `mask`, and record why the others cannot."""
    usable, rows = [], []
    for obs, v in ndvis:
        clear = _clear_fraction(v, mask)
        median = float(np.nanmedian(v[mask])) if clear > 0 else None
        if clear < s.min_clear_fraction:
            reason = f"clouds/shadow/snow: only {clear:.0%} clear"
        elif median < s.min_canopy_ndvi:
            reason = f"no crop canopy (median NDVI {median:.2f} < {s.min_canopy_ndvi})"
        else:
            reason = "ok"
            usable.append(v)
        rows.append(dict(
            date=obs.date.isoformat(), used=reason == "ok", reason=reason,
            median_ndvi=None if median is None else round(median, 3), clear_pct=round(clear * 100, 1),
        ))
    return usable, rows


def _empty_season(shape) -> Season:
    return Season(
        n_valid=np.zeros(shape, "int32"), n_flagged=np.zeros(shape, "int32"),
        persistence=np.full(shape, np.nan), median_ndvi=np.full(shape, np.nan),
        mean_relative=np.full(shape, np.nan), tiers=np.zeros(shape, "uint8"),
    )


def run_field(field: Field, start: str, end: str, out_root: Path, s: Settings = Settings(),
              max_tile_cloud: float = 80.0, observations: list[Observation] | None = None,
              unit_settings: UnitSettings = UnitSettings()) -> dict:
    out_dir = Path(out_root) / field.field_id
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = grid_for(field.geometry, field.crs)
    mask = field_mask(field, grid, s.edge_buffer_m)
    pixel_ha = grid.res**2 / 1e4

    if observations is None:
        items = search(field.geometry_wgs84, start, end, max_tile_cloud)
        log.info("%s: %d Sentinel-2 items, reading...", field.field_id, len(items))
        observations = load_observations(items, grid)
    ndvis = [(obs, ndvi(obs.red, obs.nir)) for obs in observations]

    report = dict(
        field_id=field.field_id, weedscout_version=__version__, status="ok", status_reason="",
        field_area_ha=round(field.area_ha, 2), analysed_area_ha=0.0, crs=field.crs.to_string(),
        season=dict(start=start, end=end, dates_found=len(observations)),
        settings=asdict(s), unit_settings=asdict(unit_settings), warnings=list(field.warnings),
        dates=[dict(date=o.date.isoformat(), clear_pct=round(_clear_fraction(v, mask) * 100, 1), items=o.item_ids)
               for o, v in ndvis],
        units=[],
    )

    # 1. Crop units, from every clear date of the season (bare and harvested dates included).
    clear = [(o.date.isoformat(), v) for o, v in ndvis if _clear_fraction(v, mask) >= s.min_clear_fraction]
    clear_all = [v for _, v in clear]
    units, curves = crop_units(clear_all, mask, pixel_ha, unit_settings) if mask.any() else (mask.astype("uint8"), [])
    unit_ids = real_units(units)
    n_units = len(unit_ids)
    if n_units > 1:
        report["warnings"].append(
            f"This boundary appears to contain {n_units} different crops (their seasonal NDVI curves cross). "
            "Each crop unit is analysed against itself; unit borders are excluded. "
            "If this is wrong, the boundary file may not match how the field was sown."
        )

    # 2. Anomalies within each unit.
    season = _empty_season(grid.shape)
    usable_by_unit = {}
    for u in unit_ids:
        umask = interior(units, u) & mask
        usable, rows = select_dates(ndvis, umask, s)
        unit = dict(unit_id=u, area_ha=round(float((units == u).sum() * pixel_ha), 2),
                    analysed_ha=round(float(umask.sum() * pixel_ha), 2), usable_dates=len(usable),
                    status="ok", dates=rows)
        if curves:
            unit["mean_ndvi_curve"] = {d: round(float(c), 3) for (d, _), c in zip(clear, curves[u - 1])}
        report["units"].append(unit)
        if len(usable) < s.min_dates:
            unit["status"] = "insufficient_data"
            unit["status_reason"] = (f"only {len(usable)} usable clear-sky canopy date(s); at least {s.min_dates} "
                                     "are needed to tell a persistent problem zone from a one-off")
            continue
        anomalies = [date_anomaly(v, umask, s) for v in usable]
        for row, a in zip((r for r in rows if r["used"]), anomalies):
            row["flagged_pct"] = round(float(a.flagged.sum() / a.valid.sum() * 100), 1)
        part = season_summary(usable, anomalies, umask, s)
        for name in ("n_valid", "n_flagged", "persistence", "median_ndvi", "mean_relative", "tiers"):
            getattr(season, name)[umask] = getattr(part, name)[umask]
        usable_by_unit[u] = len(usable)

    season.tiers[mask & (units == UNUSUAL)] = UNUSUAL_PATTERN
    report["analysed_area_ha"] = round(float(np.isin(season.tiers, (NORMAL, WATCH, SCOUT_FIRST)).sum() * pixel_ha), 2)
    report["season"]["usable_dates"] = max(usable_by_unit.values(), default=0)
    if not usable_by_unit:
        report["status"] = "insufficient_data"
        report["status_reason"] = (
            f"fewer than {s.min_dates} usable clear-sky canopy dates; a single date cannot tell a "
            "persistent problem zone from a one-off. Widen the date range."
        )
        write_report(out_dir, report)
        log.warning("%s: %s", field.field_id, report["status_reason"])
        return report

    # 3. Zones.
    tiers = clean_tiers(season.tiers, max(1, int(round(s.min_zone_ha / pixel_ha))))
    zones = zones_from_tiers(tiers, season, grid, units, usable_by_unit, field.geometry, s.edge_buffer_m)
    area = {t: float((tiers == t).sum() * pixel_ha) for t in (NORMAL, WATCH, SCOUT_FIRST, UNUSUAL_PATTERN)}
    report["zones"] = dict(
        scout_first_ha=round(area[SCOUT_FIRST], 2), watch_ha=round(area[WATCH], 2),
        normal_ha=round(area[NORMAL], 2), unusual_pattern_ha=round(area[UNUSUAL_PATTERN], 2),
        unusual_pattern_count=int((zones.tier == "unusual_pattern").sum()) if len(zones) else 0,
        scout_first_count=int((zones.tier == "scout_first").sum()) if len(zones) else 0,
        watch_count=int((zones.tier == "watch").sum()) if len(zones) else 0,
        flagged_share_pct=round((area[WATCH] + area[SCOUT_FIRST])
                                / max(area[NORMAL] + area[WATCH] + area[SCOUT_FIRST], 1e-9) * 100, 1),
    )
    if area[UNUSUAL_PATTERN]:
        report["warnings"].append(
            f"{area[UNUSUAL_PATTERN]:.2f} ha has a seasonal NDVI pattern unlike any crop around it (for example "
            "green early then bare, or re-greening after harvest). It is shown as 'Unusual seasonal pattern' and "
            "not scored, because comparing it with a crop it does not belong to would be meaningless."
        )

    # 4. Outputs.
    write_cog(out_dir / "scouting_tiers.tif", tiers, grid, NODATA, "scouting tier",
              {t: TIER_LABELS[t] for t in (NORMAL, WATCH, SCOUT_FIRST, UNUSUAL_PATTERN)})
    persistence_pct = np.where(np.isfinite(season.persistence), np.round(season.persistence * 100), 255).astype("uint8")
    write_cog(out_dir / "persistence_pct.tif", persistence_pct, grid, 255,
              "% of usable dates the pixel was flagged as underperforming")
    write_cog(out_dir / "season_median_ndvi.tif", season.median_ndvi.astype("float32"), grid,
              np.float32(np.nan), "median NDVI over usable dates")
    write_cog(out_dir / "crop_units.tif", units, grid, 0, "crop unit (1 = largest)",
              {UNUSUAL: "unusual seasonal pattern, not a crop unit"})
    write_vectors(out_dir, zones, field.geometry_wgs84, field.field_id)
    quicklook(
        out_dir / "quicklook.png", tiers, season.median_ndvi, grid, field.geometry, units,
        title=f"Field {field.field_id} - where to scout first",
        subtitle=(f"{start} to {end}, {report['season']['usable_dates']} clear canopy dates"
                  + (f", {n_units} crop units (dashed)" if n_units > 1 else "")
                  + ". Low vigour relative to the rest of the same crop - not a confirmed weed detection; "
                  "visit before treating."),
    )
    write_report(out_dir, report)
    log.info("%s: %d crop unit(s); scout first %.2f ha, watch %.2f ha -> %s", field.field_id, n_units,
             area[SCOUT_FIRST], area[WATCH], out_dir)
    return report
