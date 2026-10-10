"""Sentinel-2 series cached on disk, one file per field and season.

Stored as a compressed NumPy archive (.npz) holding plain arrays and a JSON string, read back with
allow_pickle=False. Never pickle: loading a pickle file runs code, so a cache file from someone else could do
anything. A file that is unreadable or inconsistent is treated as missing and downloaded again.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import numpy as np

from .boundary import Field
from .sentinel import Grid, Observation, load_observations, search

log = logging.getLogger(__name__)
FORMAT = 1  # bump when the layout below changes; other versions are ignored


def cache_path(cache: Path, field_id: str, start: str, end: str) -> Path:
    return cache / f"{field_id}_{start}_{end}.npz"


def save(path: Path, observations: list[Observation]) -> None:
    """Write the series atomically, so an interrupted run never leaves half a file behind."""
    meta = {"format": FORMAT,
            "dates": [o.date.isoformat() for o in observations],
            "item_ids": [list(o.item_ids) for o in observations]}
    shape = observations[0].red.shape if observations else (0, 0)
    stack = lambda attr, dtype: (np.stack([getattr(o, attr) for o in observations]).astype(dtype)
                                 if observations else np.empty((0, *shape), dtype))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        np.savez_compressed(f, meta=np.array(json.dumps(meta)), red=stack("red", "float32"),
                            nir=stack("nir", "float32"), scl=stack("scl", "uint8"))
    os.replace(tmp, path)


def load(path: Path) -> list[Observation] | None:
    """The cached series, or None if there is no usable cache file."""
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            red, nir, scl = z["red"], z["nir"], z["scl"]
        n = len(meta["dates"])
        if (meta.get("format") != FORMAT or len(meta["item_ids"]) != n or not (red.shape == nir.shape == scl.shape)
                or red.shape[0] != n):
            raise ValueError("inconsistent cache layout")
        return [Observation(date.fromisoformat(d), list(ids), red[i], nir[i], scl[i])
                for i, (d, ids) in enumerate(zip(meta["dates"], meta["item_ids"]))]
    except Exception as e:  # damaged, foreign or old-format file: download again rather than trust it
        log.warning("ignoring cache file %s (%s); downloading again", path.name, e)
        return None


def observations(field: Field, grid: Grid, start: str, end: str, cache: Path | None) -> list[Observation]:
    """The field's Sentinel-2 series for start..end, from the cache when possible."""
    path = cache_path(cache, field.field_id, start, end) if cache else None
    cached = load(path) if path else None
    if cached is not None and (not cached or cached[0].red.shape == grid.shape):
        return cached
    obs = load_observations(search(field.geometry_wgs84, start, end), grid)
    if path:
        save(path, obs)
    return obs
