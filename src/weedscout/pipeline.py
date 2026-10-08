"""Boundary in -> scouting map out, for one field."""

from __future__ import annotations

import logging
import json
from dataclasses import asdict, dataclass, field as dc_field
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
from .units import UNCERTAIN, UNUSUAL, UnitSettings, crop_units, interior, real_units
from .zones import clean_tiers, zone_series, zones_from_tiers

log = logging.getLogger(__name__)


def field_mask(field: Field, grid: Grid, edge_buffer_m: float) -> np.ndarray:
    """Pixels whose centre lies inside the field shrunk by `edge_buffer_m`."""
    inner = field.geometry.buffer(-edge_buffer_m) if edge_buffer_m > 0 else field.geometry
    if inner.is_empty:
        return np.zeros(grid.shape, dtype=bool)
    return rasterize([inner], out_shape=grid.shape, transform=grid.transform, fill=0, default_value=1).astype(bool)


def _clear_fraction(v: np.ndarray, mask: np.ndarray) -> float:
    return float((mask & np.isfinite(v)).sum() / mask.sum()) if mask.any() else 0.0


def main_season(medians: list[float | None], clear_ok: list[bool], min_canopy: float) -> set[int]:
    """Indices of the crop's main growing period: the run of canopy dates around the
    season's NDVI peak. A clear date without canopy (bare soil, harvest) ends a run, so
    a catch crop or regrowth after harvest is not mixed with the main crop."""
    runs, current = [], []
    for i, (m, ok) in enumerate(zip(medians, clear_ok)):
        if not ok:
            continue  # cloudy dates neither extend nor break a run
        if m >= min_canopy:
            current.append(i)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    if not runs:
        return set()
    return set(max(runs, key=lambda r: max(medians[i] for i in r)))


def select_dates(ndvis: list[tuple[Observation, np.ndarray]], mask: np.ndarray, s: Settings):
    """Decide which dates can be used for `mask`, and record why the others cannot.

    Only dates in this crop unit's own main growing period are used, so one
    whole-season window serves early crops (cereals: spring) and late crops
    (maize, beet: summer) alike."""
    clears, medians = [], []
    for _, v in ndvis:
        clear = _clear_fraction(v, mask)
        clears.append(clear)
        medians.append(float(np.nanmedian(v[mask])) if clear > 0 else None)
    clear_ok = [c >= s.min_clear_fraction for c in clears]
    season = main_season(medians, clear_ok, s.min_canopy_ndvi) if s.main_season_only else {
        i for i, (m, ok) in enumerate(zip(medians, clear_ok)) if ok and m >= s.min_canopy_ndvi}

    usable, rows = [], []
    for i, (obs, v) in enumerate(ndvis):
        clear, median = clears[i], medians[i]
        if not clear_ok[i]:
            reason = f"clouds/shadow/snow: only {clear:.0%} clear"
        elif median < s.min_canopy_ndvi:
            reason = f"no crop canopy (median NDVI {median:.2f} < {s.min_canopy_ndvi})"
        elif i not in season:
            reason = "outside this crop's main growing period (e.g. catch crop or regrowth after harvest)"
        else:
            reason = "ok"
            usable.append(v)
        rows.append(dict(
            date=obs.date.isoformat(), used=reason == "ok", reason=reason,
            median_ndvi=None if median is None else round(median, 3), clear_pct=round(clear * 100, 1),
        ))
    return usable, rows


def detectable_deficit_pct(anomalies, s: Settings) -> float:
    """Smallest NDVI deficit (as % of the crop median) that can stand out from this crop's
    own natural patchiness: |z threshold| x robust spread, never below the deficit floor.
    Validation showed weaker problems are mostly missed (docs/VALIDATION.md, section 5)."""
    spread = float(np.median([a.robust_sd / a.field_median for a in anomalies]))
    return round(100 * max(abs(s.z_threshold) * spread, s.min_relative_deficit), 1)


def _empty_season(shape) -> Season:
    return Season(
        n_valid=np.zeros(shape, "int32"), n_flagged=np.zeros(shape, "int32"),
        persistence=np.full(shape, np.nan), median_ndvi=np.full(shape, np.nan),
        mean_relative=np.full(shape, np.nan), tiers=np.zeros(shape, "uint8"),
    )


@dataclass
class Analysis:
    units: np.ndarray
    season: Season
    tiers: np.ndarray  # cleaned tier codes
    usable_by_unit: dict[int, int]
    unit_reports: list[dict]
    # per crop unit: (interior mask, [(date, ndvi, anomaly) for each usable date]) – for zone_series
    unit_dates: dict = dc_field(default_factory=dict)


def analyse(ndvis: list[tuple[Observation, np.ndarray]], mask: np.ndarray, pixel_ha: float,
            s: Settings = Settings(), unit_settings: UnitSettings = UnitSettings(),
            units: np.ndarray | None = None) -> Analysis:
    """Crop units -> per-unit anomalies -> cleaned tiers. No I/O, so it can be run
    thousands of times for calibration. Pass `units` to reuse a crop-unit split."""
    clear = [(o.date.isoformat(), v) for o, v in ndvis if _clear_fraction(v, mask) >= s.min_clear_fraction]
    curves = []
    if units is None:
        if mask.any():
            units, curves = crop_units([v for _, v in clear], mask, pixel_ha, unit_settings)
        else:
            units = mask.astype("uint8")

    season = _empty_season(mask.shape)
    usable_by_unit, unit_reports, unit_dates = {}, [], {}
    for u in real_units(units):
        umask = interior(units, u) & mask
        usable, rows = select_dates(ndvis, umask, s)
        unit = dict(unit_id=u, area_ha=round(float((units == u).sum() * pixel_ha), 2),
                    analysed_ha=round(float(umask.sum() * pixel_ha), 2), usable_dates=len(usable),
                    status="ok", dates=rows)
        if curves:
            unit["mean_ndvi_curve"] = {d: round(float(c), 3) for (d, _), c in zip(clear, curves[u - 1])}
        unit_reports.append(unit)
        if len(usable) < s.min_dates:
            unit["status"] = "insufficient_data"
            unit["status_reason"] = (f"only {len(usable)} usable clear-sky canopy date(s); at least {s.min_dates} "
                                     "are needed to tell a persistent problem zone from a one-off")
            continue
        anomalies = [date_anomaly(v, umask, s) for v in usable]
        unit_dates[u] = (umask, list(zip([r["date"] for r in rows if r["used"]], usable, anomalies)))
        for row, a in zip((r for r in rows if r["used"]), anomalies):
            row["flagged_pct"] = round(float(a.flagged.sum() / a.valid.sum() * 100), 1)
        unit["detectable_deficit_pct"] = detectable_deficit_pct(anomalies, s)
        part = season_summary(usable, anomalies, umask, s)
        for name in ("n_valid", "n_flagged", "persistence", "median_ndvi", "mean_relative", "tiers"):
            getattr(season, name)[umask] = getattr(part, name)[umask]
        usable_by_unit[u] = len(usable)

    season.tiers[mask & (units == UNUSUAL)] = UNUSUAL_PATTERN
    tiers = clean_tiers(season.tiers, max(1, int(round(s.min_zone_ha / pixel_ha))))
    return Analysis(units, season, tiers, usable_by_unit, unit_reports, unit_dates)


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

    a = analyse(ndvis, mask, pixel_ha, s, unit_settings)
    units, season, tiers, usable_by_unit = a.units, a.season, a.tiers, a.usable_by_unit
    report["units"] = a.unit_reports
    n_units = len(real_units(units))
    if n_units > 1:
        report["warnings"].append(
            f"This boundary appears to contain {n_units} different crops (their seasonal NDVI curves cross). "
            "Each crop unit is analysed against itself; unit borders are excluded. "
            "If this is wrong, the boundary file may not match how the field was sown."
        )

    report["analysed_area_ha"] = round(float(np.isin(season.tiers, (NORMAL, WATCH, SCOUT_FIRST)).sum() * pixel_ha), 2)
    report["uncertain_unit_ha"] = round(float((units == UNCERTAIN).sum() * pixel_ha), 2)
    if report["uncertain_unit_ha"]:
        report["warnings"].append(
            f"{report['uncertain_unit_ha']:.2f} ha could not be assigned to one crop unit with confidence "
            f"(fewer than {unit_settings.min_agreement:.0%} of {unit_settings.n_consensus} independent splits agreed). "
            "It is left unscored (blank on the map)."
        )
    report["season"]["usable_dates"] = max(usable_by_unit.values(), default=0)
    if not usable_by_unit:
        report["status"] = "insufficient_data"
        report["status_reason"] = (
            f"fewer than {s.min_dates} usable clear-sky canopy dates; a single date cannot tell a "
            "persistent problem zone from a one-off. Widen the date range, and match it to the crop: "
            "late crops such as maize or sugar beet only form a canopy from about June, so use e.g. June-September."
        )
        write_report(out_dir, report)
        log.warning("%s: %s", field.field_id, report["status_reason"])
        return report

    # 3. Zones.
    zones = zones_from_tiers(tiers, season, grid, units, usable_by_unit, field.geometry, s.edge_buffer_m)
    area = {t: float((tiers == t).sum() * pixel_ha) for t in (NORMAL, WATCH, SCOUT_FIRST, UNUSUAL_PATTERN)}
    report["zones"] = dict(
        scout_first_ha=round(area[SCOUT_FIRST], 2), watch_ha=round(area[WATCH], 2),
        normal_ha=round(area[NORMAL], 2), unusual_pattern_ha=round(area[UNUSUAL_PATTERN], 2),
        unusual_pattern_count=int((zones.tier == "unusual_pattern").sum()) if len(zones) else 0,
        scout_first_count=int((zones.tier == "scout_first").sum()) if len(zones) else 0,
        watch_count=int((zones.tier == "watch").sum()) if len(zones) else 0,
        scout_first_at_edge_count=int(((zones.tier == "scout_first") & zones.at_field_edge).sum()) if len(zones) else 0,
        large_zone_count=int(zones.likely_management_difference.fillna(False).astype(bool).sum()) if len(zones) else 0,
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
              {UNUSUAL: "unusual seasonal pattern, not a crop unit",
               UNCERTAIN: "crop unit uncertain, not scored"})
    write_vectors(out_dir, zones, field.geometry_wgs84, field.field_id)
    (out_dir / "zone_series.json").write_text(json.dumps(zone_series(zones, grid, a.unit_dates)), encoding="utf-8")
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
