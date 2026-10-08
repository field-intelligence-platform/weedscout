"""Field-visit kit: turn scouting zones into a blind ground-truth check, then score it.

`weedscout-visit-kit` writes one point per zone plus control points in Normal
areas, shuffled and named neutrally (P01, P02, ...) so the visitor cannot tell
which are flagged. The answer key is written to a separate file.

`weedscout-score-visits` joins the filled-in record sheet with the key and
reports how often each tier really had a problem, compared with the controls.
A zone hit rate only means something next to the control rate: if random
Normal spots have weeds just as often, the map adds nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import xy
from scipy import ndimage

from .anomaly import NORMAL, SCOUT_FIRST, UNUSUAL_PATTERN, WATCH

CATEGORIES = {"scout_first": SCOUT_FIRST, "watch": WATCH, "unusual_pattern": UNUSUAL_PATTERN}
SHEET_COLUMNS = [
    "point_id", "lat", "lon", "visited", "weeds", "weed_species", "other_cause", "notes", "photo",
]
SHEET_HELP = {
    "visited": "yes / no (could not reach)",
    "weeds": "none / few / many (within ~10 m of the point)",
    "other_cause": "none / waterlogging / compaction / nutrient / pest / disease / poor_emergence / game_damage / other",
}


def _controls(tiers_path: Path, n: int, rng, min_dist_px: int = 3):
    """Random points in Normal pixels, at least `min_dist_px` pixels from any zone."""
    with rasterio.open(tiers_path) as src:
        t = src.read(1)
        transform, crs = src.transform, src.crs
    zone = np.isin(t, (WATCH, SCOUT_FIRST, UNUSUAL_PATTERN))
    ok = (t == NORMAL) & ~ndimage.binary_dilation(zone, iterations=min_dist_px)
    ys, xs = np.nonzero(ok)
    if not len(ys):
        return gpd.GeoDataFrame(geometry=[], crs=4326)
    pick = rng.choice(len(ys), size=min(n, len(ys)), replace=False)
    x, y = xy(transform, ys[pick], xs[pick])
    return gpd.GeoDataFrame(geometry=gpd.points_from_xy(x, y), crs=crs).to_crs(4326)


def make_kit(run_dir: Path, out_dir: Path, controls_per_field: int | None = None, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    points = []
    for field_dir in sorted(p for p in run_dir.iterdir() if (p / "scouting_zones.geojson").exists()):
        zones = gpd.read_file(field_dir / "scouting_zones.geojson")
        for z in zones.itertuples():
            pt = z.geometry.representative_point()
            points.append(dict(field_id=field_dir.name, category=z.tier, zone_id=int(z.zone_id),
                               area_ha=z.area_ha, at_field_edge=bool(z.at_field_edge), lat=pt.y, lon=pt.x))
        n_ctrl = controls_per_field if controls_per_field is not None else max(3, len(zones))
        for pt in _controls(field_dir / "scouting_tiers.tif", n_ctrl, rng).geometry:
            points.append(dict(field_id=field_dir.name, category="control", zone_id=None, area_ha=None,
                               at_field_edge=None, lat=pt.y, lon=pt.x))
    order = rng.permutation(len(points))
    points = [points[i] for i in order]
    for i, p in enumerate(points, start=1):
        p["point_id"] = f"P{i:02d}"

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "record_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLUMNS)
        for p in points:
            w.writerow([p["point_id"], f"{p['lat']:.6f}", f"{p['lon']:.6f}", "", "", "", "", "", ""])
    with open(out_dir / "answer_key_DO_NOT_OPEN_BEFORE_VISIT.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["point_id", "field_id", "category", "zone_id", "area_ha", "at_field_edge"])
        w.writeheader()
        for p in points:
            w.writerow({k: p[k] for k in w.fieldnames})
    gpx = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="weedscout" xmlns="http://www.topografix.com/GPX/1/1">']
    gpx += [f'  <wpt lat="{p["lat"]:.6f}" lon="{p["lon"]:.6f}"><name>{escape(p["point_id"])}</name></wpt>'
            for p in points]
    gpx.append("</gpx>")
    (out_dir / "points.gpx").write_text("\n".join(gpx) + "\n", encoding="utf-8")
    gpd.GeoDataFrame({"point_id": [p["point_id"] for p in points]},
                     geometry=gpd.points_from_xy([p["lon"] for p in points], [p["lat"] for p in points]),
                     crs=4326).to_file(out_dir / "points.geojson", driver="GeoJSON")
    (out_dir / "HOW_TO_VISIT.md").write_text(_instructions(len(points)), encoding="utf-8")
    return points


def _instructions(n: int) -> str:
    lines = [
        "# Field visit - blind check of the scouting map", "",
        f"{n} points. Some are flagged zones and some are ordinary controls; you are not told which.",
        "Please do not open the answer key until all sheets are filled in.", "",
        "1. Load `points.gpx` (or `points.geojson`) into a phone GPS app (e.g. OsmAnd, QField, Locus).",
        "2. Ask the farmer first; stay on tramlines, do not damage the crop.",
        "3. At each point, look at the crop within about 10 m and fill one row of `record_sheet.csv`:", "",
    ]
    lines += [f"   - **{k}**: {v}" for k, v in SHEET_HELP.items()]
    lines += ["", "4. A photo per point helps; put its file name in `photo`.",
              "5. Afterwards: `weedscout-score-visits <this folder>`.", ""]
    return "\n".join(lines)


def _has(value: str, empty=("", "none", "no")) -> bool:
    return value.strip().lower() not in empty


def score(kit_dir: Path) -> dict:
    key = {r["point_id"]: r for r in csv.DictReader(open(kit_dir / "answer_key_DO_NOT_OPEN_BEFORE_VISIT.csv", encoding="utf-8"))}
    sheet = list(csv.DictReader(open(kit_dir / "record_sheet.csv", encoding="utf-8")))
    stats = {}
    for row in sheet:
        if row["visited"].strip().lower() not in ("yes", "y"):
            continue
        cat = key[row["point_id"]]["category"]
        s = stats.setdefault(cat, dict(visited=0, weeds=0, any_problem=0))
        s["visited"] += 1
        weeds = _has(row["weeds"])
        s["weeds"] += weeds
        s["any_problem"] += weeds or _has(row["other_cause"])
    for s in stats.values():
        s["weeds_pct"] = round(100 * s["weeds"] / s["visited"], 1)
        s["any_problem_pct"] = round(100 * s["any_problem"] / s["visited"], 1)
    return stats


def kit_main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="weedscout-visit-kit", description=__doc__.split("\n\n")[0])
    p.add_argument("run_dir", type=Path, help="a weedscout --out folder")
    p.add_argument("--out", type=Path, default=None, help="kit folder (default: <run_dir>/visit_kit)")
    p.add_argument("--controls-per-field", type=int, default=None, help="default: as many as zones, at least 3")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    pts = make_kit(a.run_dir, a.out or a.run_dir / "visit_kit", a.controls_per_field, a.seed)
    print(f"{len(pts)} points written to {a.out or a.run_dir / 'visit_kit'}")
    return 0


def score_main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="weedscout-score-visits")
    p.add_argument("kit_dir", type=Path)
    a = p.parse_args(argv)
    stats = score(a.kit_dir)
    if not stats:
        print("No visited points in record_sheet.csv yet.")
        return 1
    print("| category | visited | weeds | any problem |\n|---|---|---|---|")
    for cat in ("scout_first", "watch", "unusual_pattern", "control"):
        if cat in stats:
            s = stats[cat]
            print(f"| {cat} | {s['visited']} | {s['weeds_pct']}% | {s['any_problem_pct']}% |")
    (a.kit_dir / "visit_results.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    if "control" not in stats:
        print("\nNo control points visited: the zone rates cannot be compared with anything.", file=sys.stderr)
    return 0
