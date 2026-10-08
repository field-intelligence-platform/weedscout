"""Are the zones repeatable?

Split-half: the season's dates are split into two interleaved halves (1st, 3rd,
5th ... vs 2nd, 4th ...) and each half is analysed on its own. A zone that is
real should be found again from independent images.

Year-to-year: the same fields are analysed for the 2023 season. Overlap with
2024 points to a lasting cause (soil, drainage, compaction, a perennial weed
patch); no overlap is expected for causes that change with the crop.

This measures repeatability, not correctness: only a field visit can say what
a zone actually is.

Run:  python experiments/reliability.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from common import DEFAULT_BOUNDARY, ROOT, load_fields
from weedscout.anomaly import NORMAL, SCOUT_FIRST, WATCH
from weedscout.pipeline import analyse

FLAGGED = (WATCH, SCOUT_FIRST)
SCORED = (NORMAL, WATCH, SCOUT_FIRST)


def overlap(ref: np.ndarray, other: np.ndarray) -> dict:
    """How much of `ref`'s Scout-first / flagged area is flagged again in `other`,
    counted only where both analyses scored the pixel."""
    both = np.isin(ref, SCORED) & np.isin(other, SCORED)
    ref_scout = both & (ref == SCOUT_FIRST)
    ref_flag = both & np.isin(ref, FLAGGED)
    oth_flag = both & np.isin(other, FLAGGED)
    union = (ref_flag | oth_flag).sum()
    share = oth_flag.sum() / max(both.sum(), 1)
    return dict(
        scored_ha=both.sum() / 100,
        scout_ha=ref_scout.sum() / 100,
        scout_refound_pct=100 * (ref_scout & oth_flag).sum() / max(ref_scout.sum(), 1),
        flagged_refound_pct=100 * (ref_flag & oth_flag).sum() / max(ref_flag.sum(), 1),
        chance_refound_pct=100 * share,  # what random placement of `other`'s zones would give
        jaccard=(ref_flag & oth_flag).sum() / max(union, 1),
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    p.add_argument("--out", type=Path, default=ROOT / "experiments" / "results")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("pyogrio").setLevel(logging.WARNING)
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    y24 = load_fields(args.boundary, "2024-04-01", "2024-07-31")
    y23 = {f.field_id: (m, n) for f, _, m, n in load_fields(args.boundary, "2023-04-01", "2023-07-31")}
    for field, grid, mask, ndvis in y24:
        full = analyse(ndvis, mask, 0.01)
        a = analyse(ndvis[0::2], mask, 0.01, units=full.units)
        b = analyse(ndvis[1::2], mask, 0.01, units=full.units)
        rows.append(dict(field=field.field_id, test="split-half: full season vs odd dates",
                         dates=f"{max(full.usable_by_unit.values(), default=0)} vs {max(a.usable_by_unit.values(), default=0)}",
                         **overlap(full.tiers, a.tiers)))
        rows.append(dict(field=field.field_id, test="split-half: full season vs even dates",
                         dates=f"{max(full.usable_by_unit.values(), default=0)} vs {max(b.usable_by_unit.values(), default=0)}",
                         **overlap(full.tiers, b.tiers)))
        rows.append(dict(field=field.field_id, test="split-half: odd vs even dates (independent images)",
                         dates=f"{max(a.usable_by_unit.values(), default=0)} vs {max(b.usable_by_unit.values(), default=0)}",
                         **overlap(a.tiers, b.tiers)))
        m23, n23 = y23[field.field_id]
        prev = analyse(n23, m23, 0.01)
        rows.append(dict(field=field.field_id, test="2024 vs 2023 season",
                         dates=f"{max(full.usable_by_unit.values(), default=0)} vs {max(prev.usable_by_unit.values(), default=0)}",
                         units_2023=len(prev.usable_by_unit), **overlap(full.tiers, prev.tiers)))
        logging.info("%s done", field.field_id)

    df = pd.DataFrame(rows).round(2)
    df.to_csv(args.out / "reliability.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
