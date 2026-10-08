"""Split a boundary into crop units before looking for anomalies.

Official field blocks (and many farm boundary files) can hold more than one
crop. A second crop is not a problem zone, but compared with the main crop it
looks like one: in the 2024 Goettingen example a summer crop strip inside a
winter-cereal block came out as 6.4 ha of "Scout first".

Different crops have different seasonal NDVI curves - one greens up or is
harvested earlier, so their curves cross. A stressed or weedy patch of the
same crop follows the same curve, only lower. So: cluster pixels by their NDVI
time series, then merge clusters whose curves never cross.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.cluster.vq import kmeans2

FOUR_CONNECTED = ndimage.generate_binary_structure(2, 1)
UNUSUAL = 255  # unit code: seasonal pattern unlike any crop unit around it
UNCERTAIN = 254  # unit code: repeated splits disagree about which crop unit this is


@dataclass(frozen=True)
class UnitSettings:
    n_clusters: int = 5
    n_init: int = 10  # k-means restarts; the lowest-error run is kept
    crossing_ndvi: float = 0.15  # each curve must lead the other by this much...
    crossing_dates: int = 2  # ...on at least this many dates
    min_dates: int = 4
    min_unit_ha: float = 1.0
    min_patch_ha: float = 0.1  # smaller detached pieces are treated as noise
    n_consensus: int = 7  # independent splits (different seeds) voted per pixel
    min_agreement: float = 0.8  # below this share of votes a pixel's unit is 'uncertain'


def curves_cross(a: np.ndarray, b: np.ndarray, s: UnitSettings) -> bool:
    d = a - b
    return (d >= s.crossing_ndvi).sum() >= s.crossing_dates and (d <= -s.crossing_ndvi).sum() >= s.crossing_dates


def _merge_groups(centroids: np.ndarray, sizes: np.ndarray, s: UnitSettings) -> list[int]:
    """Agglomerative merge: repeatedly join the most similar pair of groups whose
    curves do not cross, recomputing the pooled (size-weighted) curve each time.
    Pairwise union-find would chain A~B~C into one group even when A and C are
    clearly different crops."""
    groups = [[i] for i in range(len(centroids))]
    curves = [centroids[i].astype(float) for i in range(len(centroids))]
    weights = [float(sizes[i]) for i in range(len(centroids))]
    while len(groups) > 1:
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if not curves_cross(curves[i], curves[j], s):
                    rms = float(np.sqrt(np.mean((curves[i] - curves[j]) ** 2)))
                    if best is None or rms < best[0]:
                        best = (rms, i, j)
        if best is None:
            break
        _, i, j = best
        w = weights[i] + weights[j]
        curves[i] = (curves[i] * weights[i] + curves[j] * weights[j]) / max(w, 1e-9)
        weights[i] = w
        groups[i] += groups.pop(j)
        curves.pop(j), weights.pop(j)
    group_of = [0] * len(centroids)
    for g, members in enumerate(groups):
        for m in members:
            group_of[m] = g
    return group_of


def _curve(series: np.ndarray, px: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(series[:, px], axis=1)


def _resolve_small(groups: np.ndarray, mask: np.ndarray, series: np.ndarray, s: UnitSettings,
                   min_unit_px: int, min_patch_px: int) -> np.ndarray:
    """Decide what happens to patches too small to be a crop unit of their own.

    - a detached piece of an existing crop (curve does not cross that crop's) stays with it;
    - otherwise it joins the neighbouring unit if its curve matches that unit's;
    - otherwise it is UNUSUAL: a pattern unlike any crop around it. It is shown
      to the user but never scored against a crop it does not belong to.
    """
    groups = groups.copy()
    for _ in range(3):
        changed = False
        ids, totals = np.unique(groups[mask], return_counts=True)
        group_total = dict(zip(ids.tolist(), totals.tolist()))
        curves = {g: _curve(series, groups == g) for g in ids if g != UNUSUAL}
        for g in ids:
            if g == UNUSUAL:
                continue
            labels, n = ndimage.label(groups == g, structure=FOUR_CONNECTED)
            sizes = np.bincount(labels.ravel(), minlength=n + 1)
            for lab in np.flatnonzero(sizes < min_unit_px):
                if lab == 0:
                    continue
                patch = labels == lab
                patch_curve = _curve(series, patch)
                if (group_total[g] >= min_unit_px and sizes[lab] >= min_patch_px
                        and not curves_cross(patch_curve, curves[g], s)):
                    continue
                ring = ndimage.binary_dilation(patch, structure=FOUR_CONNECTED) & ~patch & mask
                neighbours = groups[ring]
                neighbours = neighbours[(neighbours != g) & (neighbours != UNUSUAL)]
                target = np.bincount(neighbours).argmax() if neighbours.size else None
                if target is not None and not curves_cross(patch_curve, curves[target], s):
                    groups[patch] = target
                else:
                    groups[patch] = UNUSUAL
                changed = True
        if not changed:
            break
    return groups


def _best_kmeans(X: np.ndarray, s: UnitSettings, seed: int = 0):
    """Lowest-error result of several seeded k-means runs (a single run is seed-sensitive)."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(s.n_init):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # "one of the clusters is empty" on uniform fields
            centroids, labels = kmeans2(X, s.n_clusters, iter=30, minit="++", rng=rng)
        sse = float(((X - centroids[labels]) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, centroids, labels)
    return best[1], best[2]


def _split_once(series: np.ndarray, X: np.ndarray, mask: np.ndarray, pixel_ha: float,
                s: UnitSettings, seed: int) -> np.ndarray:
    """One crop-unit split: groups 1..n (unordered) and UNUSUAL."""
    centroids, labels = _best_kmeans(X, s, seed)
    sizes = np.bincount(labels, minlength=s.n_clusters)
    groups = np.zeros(mask.shape, dtype="uint8")
    groups[mask] = np.array(_merge_groups(centroids, sizes, s))[labels] + 1
    if groups[mask].max() == 1:
        return groups
    return _resolve_small(groups, mask, series, s,
                          max(1, int(round(s.min_unit_ha / pixel_ha))),
                          max(1, int(round(s.min_patch_ha / pixel_ha))))


def _align(run: np.ndarray, ref: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Relabel `run` so each of its groups takes the `ref` label it overlaps most."""
    out = np.zeros_like(run)
    for g in np.unique(run[mask]):
        here = mask & (run == g)
        out[here] = np.bincount(ref[here]).argmax()
    return out


def crop_units(ndvi_dates: list[np.ndarray], mask: np.ndarray, pixel_ha: float,
               s: UnitSettings = UnitSettings()) -> tuple[np.ndarray, list[np.ndarray]]:
    """Unit map (0 outside the field, 1..n by size, UNUSUAL, UNCERTAIN) and each unit's mean NDVI curve.

    `ndvi_dates` should be clear dates over the whole season, including bare-soil
    and post-harvest dates - those are where crops differ most.

    The split is repeated `n_consensus` times with different k-means seeds and
    each pixel takes its majority unit. Pixels without a clear majority
    (`min_agreement`) are UNCERTAIN: their crop is ambiguous, so they are not
    scored rather than being scored against the wrong crop.
    """
    single = np.where(mask, 1, 0).astype("uint8")
    if len(ndvi_dates) < s.min_dates or mask.sum() < 2 * s.n_clusters:
        return single, []

    series = np.stack(ndvi_dates).astype("float32")  # (dates, rows, cols)
    X = series[:, mask].T
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        X = np.where(np.isfinite(X), X, np.nanmedian(X, axis=0))

    runs = [_split_once(series, X, mask, pixel_ha, s, seed) for seed in range(s.n_consensus)]
    ref = runs[0]
    votes = np.stack([ref] + [_align(r, ref, mask) for r in runs[1:]])  # (runs, rows, cols)
    labels = np.unique(votes[:, mask])
    counts = np.stack([(votes == lab).sum(axis=0) for lab in labels])
    majority = labels[counts.argmax(axis=0)]
    agreement = counts.max(axis=0) / len(runs)

    groups = np.where(mask, majority, 0).astype("uint8")
    uncertain = mask & (agreement < s.min_agreement)
    ids, sizes = np.unique(groups[mask & ~uncertain & (groups != UNUSUAL)], return_counts=True)
    order = ids[np.argsort(-sizes)]
    units = np.zeros(mask.shape, dtype="uint8")
    units[mask & (groups == UNUSUAL)] = UNUSUAL
    for new, old in enumerate(order, start=1):
        units[(groups == old) & ~uncertain] = new
    units[uncertain] = UNCERTAIN

    curves = [_curve(series, units == u) for u in range(1, len(order) + 1)]
    if len(curves) > 1 and not any(curves_cross(curves[i], curves[j], s)
                                   for i in range(len(curves)) for j in range(i + 1, len(curves))):
        units[mask & ~np.isin(units, (UNUSUAL, UNCERTAIN))] = 1
        curves = [_curve(series, units == 1)]
    if len(curves) == 1 and not (units == UNUSUAL).any():
        units[uncertain] = 1  # a single crop has no unit border to be uncertain about
    units = _membership_check(units, X, mask, curves, s)
    curves = [_curve(series, units == u) for u in range(1, len(curves) + 1)]
    return units, curves


def _membership_check(units: np.ndarray, X: np.ndarray, mask: np.ndarray, curves: list[np.ndarray],
                      s: UnitSettings) -> np.ndarray:
    """A pixel whose own NDVI curve crosses its unit's curve does not follow that crop
    (e.g. green while the crop is bare, delayed development, re-greening after harvest).
    Clustering can attach such a patch to a neighbouring unit when the two touch; here it
    becomes UNUSUAL instead of being scored against a crop it does not follow."""
    units = units.copy()
    flat = units[mask]
    for u, curve in enumerate(curves, start=1):
        rows = np.flatnonzero(flat == u)
        d = X[rows] - curve
        crosses = (((d >= s.crossing_ndvi).sum(axis=1) >= s.crossing_dates)
                   & ((d <= -s.crossing_ndvi).sum(axis=1) >= s.crossing_dates))
        flat[rows[crosses]] = UNUSUAL
    units[mask] = flat
    return units


def real_units(units: np.ndarray) -> list[int]:
    return [int(u) for u in np.unique(units) if u not in (0, UNUSUAL, UNCERTAIN)]


def interior(units: np.ndarray, unit: int) -> np.ndarray:
    """Unit pixels not touching another unit (mixed pixels on the crop border)."""
    this = units == unit
    if (units > 0).sum() == this.sum():
        return this
    others = (units > 0) & ~this
    return this & ~ndimage.binary_dilation(others, structure=np.ones((3, 3), bool))
