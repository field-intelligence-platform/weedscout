"""Calibrate the anomaly thresholds on real Sentinel-2 data.

Sensitivity: weak patches of known size and severity are injected into the real
NDVI series of each example field (lowering NDVI by `severity` on every date at
a random clean location), and we record whether each threshold setting finds them.

False alarms: each date's anomaly map is shifted by a random offset, so any
persistent zone that still appears can only come from chance alignment of
one-off anomalies. The flagged share under this null is the false-alarm rate.

Run:  python experiments/calibrate.py            (about 10 minutes; data cached after the first run)
"""

from __future__ import annotations

import argparse
import itertools
import logging
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

from common import DEFAULT_BOUNDARY, ROOT, flagged_share, load_fields, retier
from weedscout.anomaly import NORMAL, SCOUT_FIRST, WATCH, Settings, date_anomaly
from weedscout.pipeline import analyse, select_dates
from weedscout.units import interior, real_units
from weedscout.zones import clean_tiers

Z = [-1.0, -1.5, -2.0]
DEFICIT = [0.05, 0.10, 0.15]
WATCH_P = [0.2, 0.3, 0.4]
SCOUT_P = [0.5, 0.6, 0.7]
SIZES_HA = [0.1, 0.25, 0.5, 1.0]
SEVERITY = [0.05, 0.10, 0.15, 0.20, 0.30]


def disc(shape, cy, cx, r):
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= r**2


def placements(units, mask, baseline_tiers, area_ha, n, rng):
    """Random disc-shaped patches inside the largest crop unit, away from existing zones."""
    unit = max(real_units(units), key=lambda u: (units == u).sum())
    allowed = interior(units, unit) & mask & ~ndimage.binary_dilation(
        np.isin(baseline_tiers, (WATCH, SCOUT_FIRST, 4)), iterations=2)
    r = np.sqrt(area_ha * 1e4 / np.pi) / 10.0
    centres = ndimage.binary_erosion(allowed, structure=disc((2 * int(r) + 3,) * 2, int(r) + 1, int(r) + 1, r + 0.5))
    ys, xs = np.nonzero(centres)
    if not len(ys):
        return []
    pick = rng.choice(len(ys), size=min(n, len(ys)), replace=False)
    return [disc(mask.shape, ys[i], xs[i], r) & allowed for i in pick]


def inject(ndvis, patch, severity):
    out = []
    for obs, v in ndvis:
        v2 = v.copy()
        v2[patch] = v[patch] * (1 - severity)
        out.append((obs, v2))
    return out


def sensitivity(fields, n_place, rng):
    rows = []
    for field, grid, mask, ndvis in fields:
        pixel_ha = grid.res**2 / 1e4
        base = analyse(ndvis, mask, pixel_ha)
        for area_ha, severity in itertools.product(SIZES_HA, SEVERITY):
            for k, patch in enumerate(placements(base.units, mask, base.tiers, area_ha, n_place, rng)):
                injected = inject(ndvis, patch, severity)
                for z, d in itertools.product(Z, DEFICIT):
                    s = replace(Settings(), z_threshold=z, min_relative_deficit=d)
                    a = analyse(injected, mask, pixel_ha, s, units=base.units)
                    for wp, sp in itertools.product(WATCH_P, SCOUT_P):
                        t = retier(a.season, wp, sp, max(1, round(s.min_zone_ha / pixel_ha)))
                        rows.append(dict(
                            field=field.field_id, area_ha=area_ha, severity=severity, placement=k,
                            z=z, deficit=d, watch_p=wp, scout_p=sp,
                            found=float(np.isin(t[patch], (WATCH, SCOUT_FIRST)).mean() >= 0.5),
                            found_scout=float((t[patch] == SCOUT_FIRST).mean() >= 0.5),
                        ))
        logging.info("%s: sensitivity done", field.field_id)
    return pd.DataFrame(rows)


def null_false_alarms(fields, n_shuffle, rng):
    rows = []
    for field, grid, mask, ndvis in fields:
        pixel_ha = grid.res**2 / 1e4
        base = analyse(ndvis, mask, pixel_ha)
        for z, d in itertools.product(Z, DEFICIT):
            s = replace(Settings(), z_threshold=z, min_relative_deficit=d)
            per_unit = []
            for u in real_units(base.units):
                umask = interior(base.units, u) & mask
                usable, _ = select_dates(ndvis, umask, s)
                if len(usable) < s.min_dates:
                    continue
                an = [date_anomaly(v, umask, s) for v in usable]
                per_unit.append((umask, np.stack([a.flagged for a in an]), np.stack([a.valid for a in an])))
            for i in range(n_shuffle):
                shifted = []
                for umask, flags, valid in per_unit:
                    rolled = np.stack([np.roll(f, (rng.integers(-f.shape[0], f.shape[0]),
                                                   rng.integers(-f.shape[1], f.shape[1])), (0, 1)) for f in flags])
                    n_valid = valid.sum(0)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        p = np.where(umask & (n_valid >= s.min_dates), (rolled & valid).sum(0) / n_valid, np.nan)
                    shifted.append((umask & (n_valid >= s.min_dates), p))
                for wp, sp in itertools.product(WATCH_P, SCOUT_P):
                    t = np.zeros(mask.shape, "uint8")
                    for m, p in shifted:
                        t[m] = NORMAL
                        t[m & (p >= wp)] = WATCH
                        t[m & (p >= sp)] = SCOUT_FIRST
                    t = clean_tiers(t, max(1, round(s.min_zone_ha / pixel_ha)))
                    rows.append(dict(field=field.field_id, shuffle=i, z=z, deficit=d, watch_p=wp, scout_p=sp,
                                     null_flagged=flagged_share(t),
                                     null_scout=float((t == SCOUT_FIRST).sum() / max(np.isin(t, (1, 2, 3)).sum(), 1))))
        logging.info("%s: null done", field.field_id)
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    p.add_argument("--start", default="2024-04-01")
    p.add_argument("--end", default="2024-07-31")
    p.add_argument("--placements", type=int, default=8)
    p.add_argument("--shuffles", type=int, default=30)
    p.add_argument("--out", type=Path, default=ROOT / "experiments" / "results")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("pyogrio").setLevel(logging.WARNING)
    args.out.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(42)
    fields = load_fields(args.boundary, args.start, args.end)
    sens = sensitivity(fields, args.placements, rng)
    null = null_false_alarms(fields, args.shuffles, rng)
    sens.to_csv(args.out / "sensitivity_raw.csv", index=False)
    null.to_csv(args.out / "null_raw.csv", index=False)

    keys = ["z", "deficit", "watch_p", "scout_p"]
    fa = null.groupby(keys).agg(false_alarm_flagged=("null_flagged", "mean"),
                                false_alarm_scout=("null_scout", "mean")).reset_index()
    rec = (sens.groupby(keys + ["area_ha", "severity"])[["found", "found_scout"]].mean()
           .reset_index())
    rec.to_csv(args.out / "sensitivity_by_patch.csv", index=False)
    summary = rec[(rec.area_ha >= 0.25) & (rec.severity.between(0.10, 0.20))].groupby(keys)[
        ["found", "found_scout"]].mean().reset_index().merge(fa, on=keys)
    summary = summary.rename(columns={"found": "recall_flagged", "found_scout": "recall_scout"})
    summary.sort_values(["recall_scout", "false_alarm_flagged"], ascending=[False, True]).to_csv(
        args.out / "threshold_summary.csv", index=False)
    print(summary.sort_values("recall_scout", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
