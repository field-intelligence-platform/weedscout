"""Field-relative vigour anomalies and how persistent they are over a season.

Each pixel is compared with its own field on the same date, not with a fixed
NDVI threshold. That removes most of the date, crop and sensor effects that
make absolute thresholds (v0: NDVI < 0.4) meaningless. Confidence comes from
persistence: a zone that underperforms on most clear dates is more worth a
visit than one that dips once.
"""

from __future__ import annotations

import warnings

from dataclasses import dataclass

import numpy as np

# Tier codes written to scouting_tiers.tif.
NODATA, NORMAL, WATCH, SCOUT_FIRST, UNUSUAL_PATTERN = 0, 1, 2, 3, 4
TIER_NAMES = {NORMAL: "normal", WATCH: "watch", SCOUT_FIRST: "scout_first", UNUSUAL_PATTERN: "unusual_pattern"}
TIER_LABELS = {
    NORMAL: "Normal",
    WATCH: "Watch - underperformed on some dates",
    SCOUT_FIRST: "Scout first - underperformed on most dates",
    UNUSUAL_PATTERN: "Unusual seasonal pattern - unlike the crops around it, not scored",
}


@dataclass(frozen=True)
class Settings:
    min_clear_fraction: float = 0.8  # share of the field that must be cloud-free on a date
    min_canopy_ndvi: float = 0.4  # field median; below this the crop is not up (or is harvested)
    z_threshold: float = -1.5  # robust z-score versus the field on that date
    min_relative_deficit: float = 0.10  # and at least 10 % below the field median
    min_dates: int = 3  # fewer usable dates -> no tiers at all
    watch_persistence: float = 0.3
    scout_persistence: float = 0.6
    edge_buffer_m: float = 10.0  # drop boundary pixels mixed with roads/hedges
    min_zone_ha: float = 0.1


def ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (nir - red) / (nir + red)
    out[~np.isfinite(out)] = np.nan
    return out


@dataclass
class DateAnomaly:
    field_median: float
    robust_sd: float
    relative: np.ndarray  # (ndvi - median) / median
    flagged: np.ndarray  # bool, only meaningful where `valid`
    valid: np.ndarray  # bool


def date_anomaly(ndvi_day: np.ndarray, field_mask: np.ndarray, s: Settings) -> DateAnomaly:
    valid = field_mask & np.isfinite(ndvi_day)
    values = ndvi_day[valid]
    median = float(np.median(values))
    # 1.4826 * MAD estimates the standard deviation without being dragged by the
    # very patches we are looking for; the floor stops a near-uniform field from
    # turning sensor noise into huge z-scores.
    robust_sd = max(1.4826 * float(np.median(np.abs(values - median))), 0.01)
    with np.errstate(invalid="ignore"):
        z = (ndvi_day - median) / robust_sd
        relative = (ndvi_day - median) / median
        flagged = valid & (z <= s.z_threshold) & (relative <= -s.min_relative_deficit)
    return DateAnomaly(median, robust_sd, relative, flagged, valid)


@dataclass
class Season:
    n_valid: np.ndarray  # usable observations per pixel
    n_flagged: np.ndarray
    persistence: np.ndarray  # n_flagged / n_valid, NaN where too few observations
    median_ndvi: np.ndarray
    mean_relative: np.ndarray  # mean deficit versus the field, over usable dates
    tiers: np.ndarray  # uint8 tier codes


def season_summary(
    ndvi_stack: list[np.ndarray], anomalies: list[DateAnomaly], field_mask: np.ndarray, s: Settings
) -> Season:
    valid = np.stack([a.valid for a in anomalies])
    n_valid = valid.sum(axis=0)
    n_flagged = np.stack([a.flagged for a in anomalies]).sum(axis=0)
    enough = field_mask & (n_valid >= s.min_dates)

    with np.errstate(invalid="ignore", divide="ignore"):
        persistence = np.where(enough, n_flagged / n_valid, np.nan)
    stack = np.stack([np.where(a.valid, x, np.nan) for a, x in zip(anomalies, ndvi_stack)])
    rel = np.stack([np.where(a.valid, a.relative, np.nan) for a in anomalies])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels outside the field
        median_ndvi = np.where(enough, np.nanmedian(stack, axis=0), np.nan)
        mean_relative = np.where(enough, np.nanmean(rel, axis=0), np.nan)

    tiers = np.full(field_mask.shape, NODATA, dtype="uint8")
    tiers[enough] = NORMAL
    tiers[enough & (persistence >= s.watch_persistence)] = WATCH
    tiers[enough & (persistence >= s.scout_persistence)] = SCOUT_FIRST
    return Season(n_valid, n_flagged, persistence, median_ndvi, mean_relative, tiers)
