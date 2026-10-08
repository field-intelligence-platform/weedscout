"""End-to-end on synthetic observations (no network)."""

import json

import geopandas as gpd
import numpy as np
import rasterio

from weedscout.anomaly import NODATA, NORMAL, SCOUT_FIRST, WATCH, Settings, date_anomaly
from weedscout.pipeline import field_mask, run_field
from weedscout.sentinel import grid_for
from weedscout.zones import clean_tiers

from .conftest import make_observations


def _patch(grid, rows=slice(10, 20), cols=slice(10, 20)):
    m = np.zeros(grid.shape, dtype=bool)
    m[rows, cols] = True
    return m  # 10 x 10 px = 1 ha


def test_persistent_patch_becomes_scout_first(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 8, patch=_patch(grid))
    report = run_field(square_field, "2024-05-01", "2024-07-01", tmp_path, observations=obs)

    assert report["status"] == "ok"
    assert report["season"]["usable_dates"] == 8
    assert 0.9 <= report["zones"]["scout_first_ha"] <= 1.1
    assert report["zones"]["watch_ha"] < 0.2
    assert report["zones"]["flagged_share_pct"] < 10  # v0 flagged 99.8 % of its AOI

    zones = gpd.read_file(tmp_path / "test_field" / "scouting_zones.geojson")
    assert zones.crs.to_epsg() == 4326
    top = zones.sort_values("area_ha").iloc[-1]
    assert top.tier == "scout_first"
    assert top.flagged_dates == "8 of 8"
    assert top.ndvi_deficit_pct < -30
    # Stored area agrees with the geometry measured in a metric CRS (v0 stored areas 1.75x too large).
    assert np.isclose(zones.to_crs(square_field.crs).area.iloc[zones.area_ha.idxmax()] / 1e4, top.area_ha, rtol=0.01)


def test_one_off_dip_is_only_watch_or_normal(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 8, patch=_patch(grid), patch_dates={3})
    report = run_field(square_field, "2024-05-01", "2024-07-01", tmp_path, observations=obs)
    assert report["zones"]["scout_first_ha"] == 0
    assert report["zones"]["watch_ha"] == 0  # 1/8 = 12.5 % < 30 % watch threshold


def test_uniform_field_has_no_zones(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 8, noise=0.01)
    report = run_field(square_field, "2024-05-01", "2024-07-01", tmp_path, observations=obs)
    assert report["zones"]["scout_first_ha"] == 0 and report["zones"]["watch_ha"] == 0


def test_too_few_dates_refuses_to_map(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 2, patch=_patch(grid))
    report = run_field(square_field, "2024-05-01", "2024-07-01", tmp_path, observations=obs)
    assert report["status"] == "insufficient_data"
    assert not (tmp_path / "test_field" / "scouting_tiers.tif").exists()
    assert "No scouting map produced" in (tmp_path / "test_field" / "summary.md").read_text()


def test_cloudy_and_bare_dates_are_skipped_with_reasons(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 6, patch=_patch(grid))
    obs[0].red[:] = np.nan  # fully clouded
    bare = make_observations(grid, 1, base_ndvi=0.2)[0]  # before emergence
    report = run_field(square_field, "2024-04-01", "2024-07-01", tmp_path, observations=[bare] + obs)
    reasons = [d["reason"] for d in report["units"][0]["dates"]]
    assert reasons[0].startswith("no crop canopy")
    assert reasons[1].startswith("clouds")
    assert report["season"]["usable_dates"] == 5
    assert report["dates"][1]["clear_pct"] == 0


def test_outputs_are_cogs_with_nodata(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    run_field(square_field, "2024-05-01", "2024-07-01", tmp_path,
              observations=make_observations(grid, 5, patch=_patch(grid)))
    out = tmp_path / "test_field"
    with rasterio.open(out / "scouting_tiers.tif") as src:
        assert src.dtypes[0] == "uint8" and src.nodata == NODATA
        assert src.crs.to_epsg() == 32632
        assert src.profile.get("tiled") and src.compression is not None
        a = src.read(1)
    assert a[0, 0] == NODATA  # outside the field is no-data, not "normal"
    assert set(np.unique(a)) <= {NODATA, NORMAL, WATCH, SCOUT_FIRST}
    for name in ("quicklook.png", "summary.md", "report.json", "scouting_zones_shapefile.zip",
                 "persistence_pct.tif", "season_median_ndvi.tif", "field_boundary.geojson"):
        assert (out / name).exists(), name
    json.loads((out / "report.json").read_text())


def test_edge_buffer_excludes_boundary_pixels(square_field):
    grid = grid_for(square_field.geometry, square_field.crs)
    assert field_mask(square_field, grid, 0).sum() == 1600  # 40 x 40 px
    assert field_mask(square_field, grid, 10).sum() == 38 * 38


def test_relative_deficit_guard():
    """A z-score alone would flag tiny differences in a very uniform field."""
    mask = np.ones((20, 20), dtype=bool)
    v = np.full((20, 20), 0.80)
    v[:2, :2] = 0.77  # 4 % lower: statistically odd, agronomically nothing
    a = date_anomaly(v, mask, Settings())
    assert not a.flagged.any()


def test_clean_tiers_minimum_mapping_unit():
    t = np.full((20, 20), NORMAL, dtype="uint8")
    t[0:2, 0:2] = SCOUT_FIRST  # 4 px, isolated -> normal
    t[10:20, 10:20] = WATCH  # 100 px watch zone
    t[12:14, 12:14] = SCOUT_FIRST  # 4 px island inside watch -> watch
    out = clean_tiers(t, min_pixels=10)
    assert (out[0:2, 0:2] == NORMAL).all()
    assert (out[10:20, 10:20] == WATCH).all()


def test_clean_tiers_merges_watch_fringe_into_scout_zone():
    t = np.full((20, 20), NORMAL, dtype="uint8")
    t[5:10, 5:10] = SCOUT_FIRST  # 25 px zone
    t[4, 7] = WATCH  # 1 px fringe on its rim
    t[2, 15] = WATCH  # isolated pixel attached to nothing
    t[3, 15] = SCOUT_FIRST
    out = clean_tiers(t, min_pixels=10)
    assert out[4, 7] == SCOUT_FIRST
    assert out[2, 15] == NORMAL and out[3, 15] == NORMAL


def _two_crop_observations(grid, patch=None):
    """West half winter cereal (green early, harvested late), east half summer crop (bare early)."""
    cereal = [0.70, 0.80, 0.85, 0.85, 0.80, 0.60, 0.30, 0.22]
    summer = [0.20, 0.18, 0.25, 0.45, 0.70, 0.85, 0.88, 0.88]
    obs = make_observations(grid, len(cereal))
    rng = np.random.default_rng(1)
    east = np.zeros(grid.shape, bool)
    east[:, grid.width // 2:] = True
    for o, c, sm in zip(obs, cereal, summer):
        target = np.where(east, sm, c) + rng.normal(0, 0.02, grid.shape)
        if patch is not None and c >= 0.4:
            target[patch] = c * 0.6
        o.nir = (o.red * (1 + target) / (1 - target)).astype("float32")
    return obs, east


def test_second_crop_is_a_unit_not_a_problem_zone(square_field, tmp_path):
    """v1.0 first draft flagged a summer-crop strip in a cereal block as 6.4 ha 'Scout first'."""
    grid = grid_for(square_field.geometry, square_field.crs)
    patch = _patch(grid, rows=slice(10, 20), cols=slice(6, 16))  # 1 ha, inside the cereal half
    obs, east = _two_crop_observations(grid, patch)
    report = run_field(square_field, "2024-04-01", "2024-07-31", tmp_path, observations=obs)

    assert len(report["units"]) == 2
    assert any("2 different crops" in w for w in report["warnings"])
    # The summer crop is not flagged as a whole...
    assert report["zones"]["scout_first_ha"] < 1.5
    # ...but the real patch inside the cereal is still found.
    zones = gpd.read_file(tmp_path / "test_field" / "scouting_zones.geojson")
    sf = zones[zones.tier == "scout_first"]
    assert len(sf) == 1 and 0.6 <= sf.area_ha.iloc[0] <= 1.1
    with rasterio.open(tmp_path / "test_field" / "crop_units.tif") as src:
        u = src.read(1)
    assert len(set(np.unique(u)) - {0}) == 2


def test_same_crop_with_weak_patch_stays_one_unit(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 10, patch=_patch(grid, rows=slice(5, 25), cols=slice(5, 25)))
    report = run_field(square_field, "2024-04-01", "2024-07-31", tmp_path, observations=obs)
    assert len(report["units"]) == 1
    assert report["zones"]["scout_first_ha"] >= 3.5


def test_main_season_picks_the_run_around_the_peak():
    from weedscout.pipeline import main_season

    #          spring cereal ......  harvest  catch crop
    medians = [0.6, 0.8, 0.85, None, 0.7, 0.2, 0.5, 0.55]
    clear = [True, True, True, False, True, True, True, True]
    assert main_season(medians, clear, 0.4) == {0, 1, 2, 4}  # cloudy date 3 does not break the run
    assert main_season([0.2, 0.1], [True, True], 0.4) == set()


def test_catch_crop_after_harvest_is_not_scored_with_the_main_crop(square_field, tmp_path):
    """A whole-season window must not mix the cereal with a catch crop sown after harvest."""
    grid = grid_for(square_field.geometry, square_field.crs)
    obs = make_observations(grid, 9, patch=_patch(grid), patch_dates={0, 1, 2, 3, 4})
    curve = [0.70, 0.80, 0.85, 0.85, 0.75, 0.20, 0.45, 0.55, 0.60]  # cereal, harvest, catch crop
    rng = np.random.default_rng(3)
    for i, (o, c) in enumerate(zip(obs, curve)):
        target = np.full(grid.shape, c) + rng.normal(0, 0.02, grid.shape)
        if i <= 4:
            target[_patch(grid)] = c * 0.6
        o.nir = (o.red * (1 + target) / (1 - target)).astype("float32")
    report = run_field(square_field, "2024-03-01", "2024-10-31", tmp_path, observations=obs)
    rows = report["units"][0]["dates"]
    assert [r["used"] for r in rows] == [True] * 5 + [False] * 4
    assert rows[6]["reason"].startswith("outside this crop's main growing period")
    assert report["zones"]["scout_first_ha"] >= 0.8  # the patch, judged on the cereal dates only


def test_year_option_means_whole_growing_season(tmp_path, monkeypatch):
    import weedscout.cli as cli

    seen = {}
    monkeypatch.setattr(cli, "run_field", lambda f, start, end, *a, **k: seen.update(start=start, end=end) or {"status": "ok"})
    p = tmp_path / "f.geojson"
    gpd.GeoDataFrame(geometry=[__import__("shapely").geometry.box(9.93, 51.53, 9.9358, 51.5336)], crs=4326).to_file(p)
    assert cli.main(["--boundary", str(p), "--year", "2024", "--out", str(tmp_path)]) == 0
    assert seen == {"start": "2024-03-01", "end": "2024-10-31"}


def test_large_zone_is_marked_as_possible_management_difference(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    big = _patch(grid, rows=slice(4, 24), cols=slice(4, 24))  # 4 ha of a ~14 ha unit
    run_field(square_field, "2024-05-01", "2024-07-01", tmp_path, observations=make_observations(grid, 8, patch=big))
    zones = gpd.read_file(tmp_path / "test_field" / "scouting_zones.geojson")
    top = zones.sort_values("area_ha").iloc[-1]
    assert top.likely_management_difference and top.share_of_unit_pct >= 20
    assert "management difference" in (tmp_path / "test_field" / "summary.md").read_text()


def test_detectable_deficit_reflects_field_patchiness(square_field, tmp_path):
    grid = grid_for(square_field.geometry, square_field.crs)
    smooth = run_field(square_field, "2024-05-01", "2024-07-01", tmp_path / "a",
                       observations=make_observations(grid, 6, noise=0.01))
    patchy = run_field(square_field, "2024-05-01", "2024-07-01", tmp_path / "b",
                       observations=make_observations(grid, 6, noise=0.08))
    d_smooth = smooth["units"][0]["detectable_deficit_pct"]
    d_patchy = patchy["units"][0]["detectable_deficit_pct"]
    assert d_smooth == 5.0  # floor: the minimum relative deficit
    assert d_patchy > 10  # a patchy crop hides weaker problems
    assert "cannot be told apart" in (tmp_path / "b" / "test_field" / "summary.md").read_text()
