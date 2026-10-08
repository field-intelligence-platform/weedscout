"""Write outputs a farmer or agronomist can open: COG rasters, GeoJSON,
a zipped Shapefile (what most sprayer/task-controller software imports),
a PNG map, and a plain-language summary."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from rasterio.io import MemoryFile  # noqa: E402
from rasterio.features import shapes  # noqa: E402
from rasterio.shutil import copy as rio_copy  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from .anomaly import NORMAL, SCOUT_FIRST, TIER_LABELS, UNUSUAL_PATTERN, WATCH  # noqa: E402
from .sentinel import Grid  # noqa: E402
from .units import UNUSUAL, real_units  # noqa: E402

TIER_COLORS = {NORMAL: "#d9d9d9", WATCH: "#f2b134", SCOUT_FIRST: "#c0392b", UNUSUAL_PATTERN: "#8e6bbf"}
ATTRIBUTION = (
    "Contains modified Copernicus Sentinel data, processed via Microsoft Planetary Computer."
)


def write_cog(path: Path, array: np.ndarray, grid: Grid, nodata, description: str, categories=None):
    profile = dict(
        driver="GTiff", width=grid.width, height=grid.height, count=1,
        dtype=array.dtype.name, crs=grid.crs, transform=grid.transform, nodata=nodata,
    )
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(array, 1)
            dst.set_band_description(1, description)
            if categories:
                dst.update_tags(1, **{f"class_{k}": v for k, v in categories.items()})
        with mem.open() as src:
            rio_copy(src, path, driver="COG", compress="DEFLATE", overview_resampling="nearest")


def write_vectors(out_dir: Path, zones: gpd.GeoDataFrame, field_wgs84, field_id: str):
    zones.to_file(out_dir / "scouting_zones.geojson", driver="GeoJSON")
    gpd.GeoDataFrame({"field_id": [field_id]}, geometry=[field_wgs84], crs=4326).to_file(
        out_dir / "field_boundary.geojson", driver="GeoJSON"
    )
    if len(zones):
        # Shapefile field names are limited to 10 characters.
        shp = zones.rename(columns={
            "persistence_pct": "persist_pc", "flagged_dates": "flag_dates",
            "ndvi_deficit_pct": "deficit_pc", "median_ndvi": "med_ndvi",
            "usable_dates_in_season": "n_dates", "at_field_edge": "at_edge",
        })
        with tempfile.TemporaryDirectory() as tmp:
            shp.to_file(Path(tmp) / "scouting_zones.shp")
            shutil.make_archive(str(out_dir / "scouting_zones_shapefile"), "zip", tmp)


def _unit_outlines(units: np.ndarray, grid: Grid) -> gpd.GeoDataFrame:
    crops = np.where(units == UNUSUAL, 0, units).astype("uint8")
    polys = [(shape(g), int(v)) for g, v in shapes(crops, mask=crops > 0, transform=grid.transform)]
    gdf = gpd.GeoDataFrame({"unit": [v for _, v in polys]}, geometry=[p for p, _ in polys])
    return gdf.dissolve("unit").reset_index()


def quicklook(path: Path, tiers, median_ndvi, grid: Grid, field_utm, units, title: str, subtitle: str):
    extent = (
        grid.transform.c, grid.transform.c + grid.width * grid.res,
        grid.transform.f - grid.height * grid.res, grid.transform.f,
    )
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), constrained_layout=True)
    boundary = gpd.GeoSeries([field_utm])
    outlines = _unit_outlines(units, grid) if len(real_units(units)) > 1 else None

    ax = axes[0]
    im = ax.imshow(np.ma.masked_invalid(median_ndvi), cmap="RdYlGn", vmin=0.2, vmax=0.9, extent=extent)
    fig.colorbar(im, ax=ax, shrink=0.75, label="Season median NDVI (usable dates)")
    ax.set_title("Crop vigour")

    ax = axes[1]
    cmap = ListedColormap(["#ffffff00"] + [TIER_COLORS[t] for t in (NORMAL, WATCH, SCOUT_FIRST, UNUSUAL_PATTERN)])
    ax.imshow(np.ma.masked_equal(tiers, 0), cmap=cmap, vmin=-0.5, vmax=4.5, extent=extent, interpolation="nearest")
    shown = [SCOUT_FIRST, WATCH, NORMAL] + ([UNUSUAL_PATTERN] if (tiers == UNUSUAL_PATTERN).any() else [])
    handles = [Patch(color=TIER_COLORS[t], label=TIER_LABELS[t]) for t in shown]
    if outlines is not None:
        handles.append(Line2D([], [], color="#1f4e9c", linestyle="--", label="Crop unit border"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), fontsize=9, frameon=False)
    ax.set_title("Scouting priority")

    for ax in axes:
        boundary.boundary.plot(ax=ax, color="black", linewidth=1.2)
        if outlines is not None:
            outlines.boundary.plot(ax=ax, color="#1f4e9c", linewidth=1.1, linestyle="--")
            for row in outlines.itertuples():
                pt = row.geometry.representative_point()
                ax.text(pt.x, pt.y, f"U{row.unit}", color="#1f4e9c", fontsize=9, fontweight="bold",
                        ha="center", va="center")
        ax.set_xticks([]), ax.set_yticks([])
        ax.set_xlabel(""), ax.set_ylabel("")
        ax.set_xlim(extent[0], extent[1]), ax.set_ylim(extent[2], extent[3])
        ax.set_aspect("equal")
        x0, y0 = extent[0] + 0.05 * (extent[1] - extent[0]), extent[2] + 0.04 * (extent[3] - extent[2])
        ax.plot([x0, x0 + 100], [y0, y0], color="black", linewidth=3)
        ax.text(x0 + 50, y0 + 0.015 * (extent[3] - extent[2]), "100 m", ha="center", fontsize=8)

    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.text(0.5, -0.09, subtitle + "\n" + ATTRIBUTION, ha="center", fontsize=8, color="#444444", wrap=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _short(row: dict) -> str:
    if row["used"]:
        return f"used ({row['median_ndvi']:.2f})"
    if row["reason"].startswith("clouds"):
        return "cloud"
    return f"no canopy ({row['median_ndvi']:.2f})"


def write_report(out_dir: Path, report: dict):
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    s = report["settings"]
    lines = [f"# Scouting summary - field {report['field_id']}", ""]
    if report["status"] != "ok":
        lines += [f"**No scouting map produced:** {report['status_reason']}", ""]
    else:
        z = report["zones"]
        lines += [
            f"- Field area: {report['field_area_ha']:.1f} ha ({report['analysed_area_ha']:.1f} ha analysed; "
            f"a {s['edge_buffer_m']:.0f} m edge buffer and crop-unit borders are excluded)",
            f"- Season: {report['season']['start']} to {report['season']['end']}, "
            f"{report['season']['dates_found']} Sentinel-2 dates found",
            f"- **Scout first:** {z['scout_first_ha']:.2f} ha in {z['scout_first_count']} zone(s)",
            f"- **Watch:** {z['watch_ha']:.2f} ha in {z['watch_count']} zone(s)",
            f"- Normal: {z['normal_ha']:.2f} ha",
        ]
        if z["unusual_pattern_ha"]:
            lines.append(f"- Unusual seasonal pattern (not scored): {z['unusual_pattern_ha']:.2f} ha "
                         f"in {z['unusual_pattern_count']} zone(s)")
    lines += ["", "## Crop units", ""]
    for u in report["units"]:
        status = (f"{u['usable_dates']} usable dates" if u["status"] == "ok"
                  else f"not mapped - {u.get('status_reason', u['status'])}")
        lines.append(f"- **U{u['unit_id']}**: {u['area_ha']:.1f} ha, {status}")
    if report["status"] == "ok":
        lines += [
            "", "## What this means", "",
            "Zones are parts of a crop unit whose NDVI was clearly below the rest of the same unit "
            f"(robust z <= {s['z_threshold']} and at least {s['min_relative_deficit'] * 100:.0f}% below its median) "
            f"on many clear dates: Watch = {s['watch_persistence']:.0%} or more of dates, Scout first = "
            f"{s['scout_persistence']:.0%} or more. Low vigour can come from weeds, but equally from waterlogging, "
            "compaction, nutrient deficiency, pests, game damage or poor emergence. **Visit these zones before "
            "deciding on any treatment.** Sentinel-2 pixels are 10 m; individual weeds are not visible.",
        ]
    for w in report.get("warnings", []):
        lines += ["", f"> Note: {w}"]

    unit_ids = [u["unit_id"] for u in report["units"]]
    lines += ["", "## Dates (median NDVI in brackets)", "",
              "| date | field clear % | " + " | ".join(f"U{u}" for u in unit_ids) + " |",
              "|---|---|" + "---|" * len(unit_ids)]
    for i, d in enumerate(report["dates"]):
        cells = [_short(u["dates"][i]) for u in report["units"]]
        lines.append(f"| {d['date']} | {d['clear_pct']:.0f} | " + " | ".join(cells) + " |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
