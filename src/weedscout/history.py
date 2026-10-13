"""Multi-year view: which zones keep coming back?

Each season is analysed on its own (own crop units, own dates), exactly as
`weedscout` does. Per pixel we then count in how many seasons it was flagged
(Watch or Scout first) out of the seasons in which it could be scored.

A zone flagged year after year points to a lasting cause - a wet hollow,
compaction, a perennial weed patch - and deserves more attention than a
one-season blip. Because some overlap happens by chance, every result is
compared with the recurring area expected if each year's zones had been
placed independently.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from rasterio.features import shapes  # noqa: E402
from scipy import ndimage  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from . import __version__  # noqa: E402
from .anomaly import NORMAL, SCOUT_FIRST, WATCH, Settings, ndvi  # noqa: E402
from .boundary import BoundaryError, Field, read_fields  # noqa: E402
from .cache import observations as cached_observations  # noqa: E402
from .export import ATTRIBUTION, write_cog  # noqa: E402
from .pipeline import analyse, field_mask  # noqa: E402
from .sentinel import Grid, grid_for  # noqa: E402
from .units import UnitSettings  # noqa: E402

log = logging.getLogger(__name__)

NODATA, NEVER, ONCE, RECURRING, CHRONIC = 0, 1, 2, 3, 4
CLASS_NAMES = {NEVER: "not_flagged", ONCE: "flagged_once", RECURRING: "recurring", CHRONIC: "chronic"}
CLASS_LABELS = {
    NEVER: "Not flagged in any season",
    ONCE: "Flagged in one season only",
    RECURRING: "Recurring - flagged in 2 or more seasons",
    CHRONIC: "Chronic - flagged in at least half of the seasons (3 or more)",
}
CLASS_COLORS = {NEVER: "#d9d9d9", ONCE: "#f6d28b", RECURRING: "#e07b39", CHRONIC: "#8c1d18"}
MIN_SCORED_YEARS = 3


def _observations(field: Field, grid: Grid, start: str, end: str, cache: Path | None):
    return cached_observations(field, grid, start, end, cache)


def chance_recurring_share(p_by_year: list[float]) -> float:
    """P(flagged in >= 2 seasons) for a pixel if each season's flagging were independent,
    with season y flagging a share p_y of the field (Poisson-binomial)."""
    dist = np.zeros(len(p_by_year) + 1)
    dist[0] = 1.0
    for p in p_by_year:
        dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p
        dist[0] *= 1 - p
    return float(dist[2:].sum())


def classify(flagged: np.ndarray, scored: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """flagged/scored: (years, rows, cols) bool -> (classes, years_flagged, years_scored)."""
    years_flagged = (flagged & scored).sum(axis=0)
    years_scored = scored.sum(axis=0)
    classes = np.zeros(flagged.shape[1:], dtype="uint8")
    ok = years_scored >= MIN_SCORED_YEARS
    classes[ok] = NEVER
    classes[ok & (years_flagged == 1)] = ONCE
    classes[ok & (years_flagged >= 2)] = RECURRING
    classes[ok & (years_flagged >= 3) & (years_flagged >= years_scored / 2)] = CHRONIC
    return classes, years_flagged, years_scored


def _clean(classes: np.ndarray, min_pixels: int) -> np.ndarray:
    """Recurring/chronic patches below the minimum mapping unit fall back to 'once'."""
    out = classes.copy()
    four = ndimage.generate_binary_structure(2, 1)
    labels, n = ndimage.label(np.isin(out, (RECURRING, CHRONIC)), structure=four)
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    out[(sizes < min_pixels)[labels] & (labels > 0)] = ONCE
    labels, n = ndimage.label(out == CHRONIC, structure=four)
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    out[(sizes < min_pixels)[labels] & (labels > 0)] = RECURRING
    return out


def run_history(field: Field, years: list[int], season: tuple[str, str], out_root: Path,
                s: Settings = Settings(), unit_settings: UnitSettings = UnitSettings(),
                cache: Path | None = None) -> dict:
    out_dir = Path(out_root) / field.field_id
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = grid_for(field.geometry, field.crs)
    mask = field_mask(field, grid, s.edge_buffer_m)
    pixel_ha = grid.res**2 / 1e4

    flagged, scored, per_year = [], [], []
    for year in years:
        start, end = f"{year}-{season[0]}", f"{year}-{season[1]}"
        obs = _observations(field, grid, start, end, cache)
        a = analyse([(o, ndvi(o.red, o.nir)) for o in obs], mask, pixel_ha, s, unit_settings)
        sc = np.isin(a.tiers, (NORMAL, WATCH, SCOUT_FIRST))
        fl = np.isin(a.tiers, (WATCH, SCOUT_FIRST))
        flagged.append(fl)
        scored.append(sc)
        per_year.append(dict(
            year=year, dates_found=len(obs), usable_dates=max(a.usable_by_unit.values(), default=0),
            crop_units=len(a.usable_by_unit), scored_ha=round(float(sc.sum() * pixel_ha), 2),
            flagged_ha=round(float(fl.sum() * pixel_ha), 2),
            flagged_share=round(float(fl.sum() / max(sc.sum(), 1)), 4),
            status="ok" if sc.any() else "insufficient_data",
        ))
        log.info("%s %d: %d usable dates, %.1f%% flagged", field.field_id, year,
                 per_year[-1]["usable_dates"], 100 * per_year[-1]["flagged_share"])

    flagged, scored = np.stack(flagged), np.stack(scored)
    classes, years_flagged, years_scored = classify(flagged, scored)
    classes = _clean(classes, max(1, int(round(s.min_zone_ha / pixel_ha))))
    analysed = classes > 0
    seasons_ok = [y for y in per_year if y["status"] == "ok"]
    observed = float(np.isin(classes, (RECURRING, CHRONIC)).sum() / max(analysed.sum(), 1))
    expected = chance_recurring_share([y["flagged_share"] for y in seasons_ok]) if seasons_ok else 0.0

    zones = _zones(classes, flagged, scored, years, grid)
    report = dict(
        field_id=field.field_id, weedscout_version=__version__, years=years,
        season=dict(start=season[0], end=season[1]), settings=asdict(s), seasons=per_year,
        analysed_ha=round(float(analysed.sum() * pixel_ha), 2),
        area_ha={CLASS_NAMES[c]: round(float((classes == c).sum() * pixel_ha), 2) for c in CLASS_NAMES},
        recurring_share_observed=round(observed, 4), recurring_share_expected_by_chance=round(expected, 4),
        recurring_vs_chance=round(observed / expected, 2) if expected > 0 else None,
    )

    write_cog(out_dir / "recurrence.tif", classes, grid, NODATA, "multi-season recurrence class",
              {c: CLASS_LABELS[c] for c in CLASS_LABELS})
    yf = np.where(analysed, years_flagged, 255).astype("uint8")
    write_cog(out_dir / "years_flagged.tif", yf, grid, 255, "number of seasons the pixel was flagged")
    zones.to_file(out_dir / "recurring_zones.geojson", driver="GeoJSON")
    _quicklook(out_dir / "history_quicklook.png", classes, flagged, scored, years, grid, field.geometry, report)
    (out_dir / "history.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "history_summary.md").write_text(_summary(report), encoding="utf-8")
    return report


def _zones(classes, flagged, scored, years, grid: Grid) -> gpd.GeoDataFrame:
    records = []
    four = ndimage.generate_binary_structure(2, 1)
    for cls in (CHRONIC, RECURRING):
        labels, _ = ndimage.label(classes == cls, structure=four)
        geoms = {}
        for geom, v in shapes(labels.astype("int32"), mask=labels > 0, transform=grid.transform):
            geoms.setdefault(int(v), []).append(shape(geom))
        for lab, parts in geoms.items():
            px = labels == lab
            yrs = [y for y, f, sc in zip(years, flagged, scored) if f[px].mean() >= 0.5]
            records.append(dict(
                class_=CLASS_NAMES[cls], label=CLASS_LABELS[cls], area_ha=round(float(px.sum() * grid.res**2 / 1e4), 2),
                seasons_flagged=", ".join(map(str, yrs)), n_seasons_flagged=len(yrs),
                n_seasons_scored=int(np.median(scored[:, px].sum(axis=0))),
                geometry=parts[0] if len(parts) == 1 else gpd.GeoSeries(parts).union_all(),
            ))
    cols = ["class_", "label", "area_ha", "seasons_flagged", "n_seasons_flagged", "n_seasons_scored", "geometry"]
    if not records:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=4326).rename(columns={"class_": "class"})
    gdf = gpd.GeoDataFrame(records, columns=cols, geometry="geometry", crs=grid.crs).to_crs(4326)
    return gdf.rename(columns={"class_": "class"})


def _quicklook(path, classes, flagged, scored, years, grid: Grid, field_utm, report):
    extent = (grid.transform.c, grid.transform.c + grid.width * grid.res,
              grid.transform.f - grid.height * grid.res, grid.transform.f)
    n = len(years)
    fig = plt.figure(figsize=(3.0 * max(n, 4), 9), constrained_layout=True)
    gs = fig.add_gridspec(2, n, height_ratios=[1, 2.2])
    boundary = gpd.GeoSeries([field_utm])
    for i, y in enumerate(years):
        ax = fig.add_subplot(gs[0, i])
        img = np.where(scored[i], np.where(flagged[i], 2, 1), 0)
        ax.imshow(np.ma.masked_equal(img, 0), cmap=ListedColormap(["#d9d9d9", "#c0392b"]), vmin=1, vmax=2,
                  extent=extent, interpolation="nearest")
        boundary.boundary.plot(ax=ax, color="black", linewidth=0.8)
        share = next(s["flagged_share"] for s in report["seasons"] if s["year"] == y)
        ax.set_title(f"{y}: {share:.0%} flagged" if scored[i].any() else f"{y}: no map", fontsize=9)
        ax.set_xticks([]), ax.set_yticks([])
        ax.set_xlabel(""), ax.set_ylabel("")
        ax.set_xlim(extent[0], extent[1]), ax.set_ylim(extent[2], extent[3])
    ax = fig.add_subplot(gs[1, :])
    cmap = ListedColormap(["#ffffff00"] + [CLASS_COLORS[c] for c in (NEVER, ONCE, RECURRING, CHRONIC)])
    ax.imshow(np.ma.masked_equal(classes, 0), cmap=cmap, vmin=-0.5, vmax=4.5, extent=extent, interpolation="nearest")
    boundary.boundary.plot(ax=ax, color="black", linewidth=1.2)
    ax.legend(handles=[Patch(color=CLASS_COLORS[c], label=CLASS_LABELS[c]) for c in (CHRONIC, RECURRING, ONCE, NEVER)],
              loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9, frameon=False)
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_xlabel(""), ax.set_ylabel("")
    ax.set_xlim(extent[0], extent[1]), ax.set_ylim(extent[2], extent[3])
    ratio = report["recurring_vs_chance"]
    ax.set_title(f"Field {report['field_id']} - recurring low-vigour zones, {years[0]}-{years[-1]}"
                 + (f"  (recurring area {ratio:.1f}x what chance would give)" if ratio else ""), fontsize=11)
    fig.text(0.5, -0.01, "Each season analysed on its own; zones relative to the same crop that season. "
             "Not a confirmed weed detection.\n" + ATTRIBUTION, ha="center", fontsize=8, color="#444444")
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def _summary(r: dict) -> str:
    a = r["area_ha"]
    lines = [f"# Multi-season summary - field {r['field_id']}", "",
             f"Seasons {r['years'][0]}-{r['years'][-1]} ({r['season']['start']} to {r['season']['end']} each year). "
             f"{r['analysed_ha']:.1f} ha could be scored in at least {MIN_SCORED_YEARS} seasons.", "",
             f"- **Chronic** (flagged in at least half of the seasons): {a['chronic']:.2f} ha",
             f"- **Recurring** (flagged in 2 or more seasons): {a['recurring']:.2f} ha",
             f"- Flagged in one season only: {a['flagged_once']:.2f} ha",
             f"- Never flagged: {a['not_flagged']:.2f} ha", ""]
    obs, exp = r["recurring_share_observed"], r["recurring_share_expected_by_chance"]
    if r["recurring_vs_chance"] is None:
        lines.append("Not enough usable seasons to compare with chance.")
    else:
        verdict = ("clearly more than chance: these zones have a lasting cause worth investigating"
                   if obs > 2 * exp else
                   "no more than chance alone would give: zones mostly change from season to season"
                   if obs <= 1.25 * exp else
                   "somewhat more than chance: a weak sign of lasting causes")
        lines.append(f"Recurring + chronic area: **{obs:.1%}** of the field, against **{exp:.1%}** expected by chance "
                     f"if each season's zones were placed independently - {verdict}.")
    lines += ["", "| season | usable dates | crop units | flagged |", "|---|---|---|---|"]
    for s in r["seasons"]:
        lines.append(f"| {s['year']} | {s['usable_dates']} | {s['crop_units']} | "
                     + (f"{s['flagged_share']:.1%}" if s["status"] == "ok" else "no map") + " |")
    return "\n".join(lines) + "\n"


def _parse_years(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(y) for y in text.split(",")]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="weedscout-history", description="Which scouting zones recur across seasons?")
    p.add_argument("--boundary", required=True)
    p.add_argument("--years", default="2019-2024", help="e.g. 2019-2024 or 2020,2022,2024")
    p.add_argument("--season", default="03-01:10-31", help="MM-DD:MM-DD window applied to every year")
    p.add_argument("--out", default="outputs/history")
    p.add_argument("--cache", default="outputs/cache", help="folder for downloaded Sentinel-2 series ('' = none)")
    p.add_argument("--id-column")
    p.add_argument("--edge-buffer-m", type=float, default=Settings.edge_buffer_m)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("pyogrio").setLevel(logging.WARNING)
    years = _parse_years(a.years)
    if len(years) < MIN_SCORED_YEARS:
        logging.error("need at least %d seasons", MIN_SCORED_YEARS)
        return 2
    try:
        fields = read_fields(a.boundary, a.id_column)
    except BoundaryError as e:
        logging.error("%s", e)
        return 2
    start, end = a.season.split(":")
    s = Settings(edge_buffer_m=a.edge_buffer_m)
    for f in fields:
        r = run_history(f, years, (start, end), Path(a.out), s, cache=Path(a.cache) if a.cache else None)
        logging.info("%s: recurring %.1f%% of field vs %.1f%% by chance", f.field_id,
                     100 * r["recurring_share_observed"], 100 * r["recurring_share_expected_by_chance"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
