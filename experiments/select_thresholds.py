"""Apply the threshold-selection rule across one or more calibrated seasons.

Rule: among settings with chance false alarms <= --max-false-alarm and every real
field <= --max-flagged flagged in EVERY season, pick the highest Scout-first
recall in the worst season (recall on 0.25-1 ha patches with a 10-20 % deficit).

Run:  python experiments/select_thresholds.py experiments/results experiments/results_2023
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

KEYS = ["z", "deficit", "watch_p", "scout_p"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("result_dirs", type=Path, nargs="+", help="folders written by calibrate.py, one per season")
    p.add_argument("--max-false-alarm", type=float, default=0.01)
    p.add_argument("--max-flagged", type=float, default=0.15, help="scouting budget per real field")
    a = p.parse_args()

    merged = None
    for i, d in enumerate(a.result_dirs):
        s = pd.read_csv(d / "threshold_summary.csv")
        s = s[KEYS + ["recall_scout", "recall_flagged", "false_alarm_flagged", "real_flagged_max"]]
        s = s.rename(columns={c: f"{c}_{i}" for c in s.columns if c not in KEYS})
        merged = s if merged is None else merged.merge(s, on=KEYS)

    n = len(a.result_dirs)
    ok = merged.copy()
    for i in range(n):
        ok = ok[(ok[f"false_alarm_flagged_{i}"] <= a.max_false_alarm) & (ok[f"real_flagged_max_{i}"] <= a.max_flagged)]
    if ok.empty:
        print("No setting meets the rule in every season; relax the budget or widen the grid.")
        return 1
    ok = ok.assign(worst_recall=ok[[f"recall_scout_{i}" for i in range(n)]].min(axis=1))
    ok = ok.sort_values(["worst_recall"] + [f"recall_flagged_{i}" for i in range(n)], ascending=False)
    print("Seasons:", ", ".join(f"{i} = {d}" for i, d in enumerate(a.result_dirs)))
    print(ok.head(5).round(3).to_string(index=False))
    best = ok.iloc[0]
    print(f"\nSelected: z_threshold={best.z}, min_relative_deficit={best.deficit}, "
          f"watch_persistence={best.watch_p}, scout_persistence={best.scout_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
