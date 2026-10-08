import csv

import numpy as np

from weedscout.pipeline import run_field
from weedscout.sentinel import grid_for
from weedscout.visit import make_kit, score

from .conftest import make_observations


def _run(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    patch = np.zeros(grid.shape, bool)
    patch[10:20, 10:20] = True
    run_field(square_field, "2024-05-01", "2024-07-01", tmp_path / "run",
              observations=make_observations(grid, 8, patch=patch))
    return tmp_path / "run"


def test_kit_is_blind_and_has_controls(square_field, tmp_path):
    points = make_kit(_run(square_field, tmp_path), tmp_path / "kit")
    cats = [p["category"] for p in points]
    assert cats.count("scout_first") == 1 and cats.count("control") >= 3
    sheet = (tmp_path / "kit" / "record_sheet.csv").read_text()
    assert "scout" not in sheet and "control" not in sheet  # visitor cannot see the category
    assert (tmp_path / "kit" / "points.gpx").read_text().count("<wpt") == len(points)


def test_scoring_compares_zones_with_controls(square_field, tmp_path):
    kit = tmp_path / "kit"
    points = make_kit(_run(square_field, tmp_path), kit)
    rows = list(csv.DictReader(open(kit / "record_sheet.csv", encoding="utf-8")))
    cat = {p["point_id"]: p["category"] for p in points}
    for r in rows:  # pretend: weeds in the flagged zone, nothing at the controls
        r["visited"] = "yes"
        r["weeds"] = "many" if cat[r["point_id"]] == "scout_first" else "none"
        r["other_cause"] = "none"
    with open(kit / "record_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    s = score(kit)
    assert s["scout_first"]["weeds_pct"] == 100 and s["control"]["weeds_pct"] == 0
