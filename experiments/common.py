"""Shared helpers for the validation experiments: cached Sentinel-2 loading and tier recomputation."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np

from weedscout.anomaly import NORMAL, SCOUT_FIRST, WATCH, ndvi
from weedscout.boundary import read_fields
from weedscout.pipeline import field_mask
from weedscout.sentinel import grid_for, load_observations, search
from weedscout.zones import clean_tiers

log = logging.getLogger("experiments")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = ROOT / "data" / "fields" / "goettingen_example_fields.geojson"
CACHE = ROOT / "outputs" / "cache"  # git-ignored


def load_fields(boundary: Path, start: str, end: str, edge_buffer_m: float = 10.0):
    """[(field, grid, mask, ndvis)] with the Sentinel-2 series cached on disk per field and season."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = []
    for field in read_fields(boundary):
        grid = grid_for(field.geometry, field.crs)
        mask = field_mask(field, grid, edge_buffer_m)
        path = CACHE / f"{field.field_id}_{start}_{end}.pkl"
        if path.exists():
            observations = pickle.loads(path.read_bytes())
        else:
            log.info("%s %s..%s: downloading Sentinel-2", field.field_id, start, end)
            observations = load_observations(search(field.geometry_wgs84, start, end), grid)
            path.write_bytes(pickle.dumps(observations))
        out.append((field, grid, mask, [(o, ndvi(o.red, o.nir)) for o in observations]))
    return out


def retier(season, watch: float, scout: float, min_pixels: int) -> np.ndarray:
    """Tiers for other persistence thresholds without re-running the anomaly step."""
    t = season.tiers.copy()
    scored = np.isin(t, (NORMAL, WATCH, SCOUT_FIRST))
    p = season.persistence
    with np.errstate(invalid="ignore"):
        t[scored] = NORMAL
        t[scored & (p >= watch)] = WATCH
        t[scored & (p >= scout)] = SCOUT_FIRST
    return clean_tiers(t, min_pixels)


def flagged_share(tiers: np.ndarray) -> float:
    scored = np.isin(tiers, (NORMAL, WATCH, SCOUT_FIRST)).sum()
    return float(np.isin(tiers, (WATCH, SCOUT_FIRST)).sum() / max(scored, 1))
