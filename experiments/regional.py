"""Do the default thresholds hold in every region, not just on average?

Reads the per-field results of calibrate.py for one or more seasons and reports,
per region and season, under the *default* settings:
  recall      share of injected 0.25-1 ha, 10-20 % patches found as Scout first
  chance FA   flagged share under the shifted-anomaly null
  flagged     share of each real field flagged (mean and worst field)

Run:  python experiments/regional.py --boundary data/fields/germany_calibration_fields.geojson \
          experiments/germany_2024 experiments/germany_2023
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from common import flagged_share, load_fields
from weedscout.anomaly import Settings
from weedscout.pipeline import analyse

S = Settings()
DEFAULT = dict(z=S.z_threshold, deficit=S.min_relative_deficit, watch_p=S.watch_persistence, scout_p=S.scout_persistence)


def pick(df: pd.DataFrame) -> pd.DataFrame:
    q = True
    for k, v in DEFAULT.items():
        q = q & ((df[k] - v).abs() < 1e-9)
    return df[q]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boundary", type=Path, required=True)
    p.add_argument("result_dirs", type=Path, nargs="+")
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    region = gpd.read_file(a.boundary).set_index("field_id")["region"].to_dict()

    rows = []
    for d in a.result_dirs:
        sens = pick(pd.read_csv(d / "sensitivity_raw.csv", dtype={"field": str}))
        sens = sens[(sens.area_ha >= 0.25) & sens.severity.between(0.10, 0.20)]
        null = pick(pd.read_csv(d / "null_raw.csv", dtype={"field": str}))
        start, end = (lambda t: (t["start"], t["end"]))(pd.read_json(d / "season.json", typ="series"))
        flagged = {f.field_id: flagged_share(analyse(n, m, g.res**2 / 1e4).tiers)
                   for f, g, m, n in load_fields(a.boundary, start, end)}
        for reg in sorted(set(region.values())):
            fids = [f for f, r in region.items() if r == reg]
            fl = [flagged[f] for f in fids if f in flagged]
            rows.append(dict(
                season=start[:4], region=reg, fields=len(fids),
                recall_scout=sens[sens.field.isin(fids)].found_scout.mean(),
                chance_false_alarm=null[null.field.isin(fids)].null_flagged.mean(),
                flagged_mean=sum(fl) / len(fl), flagged_worst_field=max(fl),
            ))
    out = pd.DataFrame(rows)
    out.to_csv(a.result_dirs[0].parent / "regional_check.csv", index=False)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
