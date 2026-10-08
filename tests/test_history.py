from datetime import timedelta

import geopandas as gpd
import numpy as np
import pytest

import weedscout.history as H
from weedscout.history import CHRONIC, NEVER, ONCE, RECURRING, chance_recurring_share, classify
from weedscout.sentinel import grid_for

from .conftest import make_observations


def test_chance_recurring_share():
    assert chance_recurring_share([0.0, 0.0, 0.0]) == 0.0
    assert chance_recurring_share([1.0, 1.0, 0.0]) == pytest.approx(1.0)
    # two seasons at 10 %: P(both) = 1 %
    assert chance_recurring_share([0.1, 0.1]) == pytest.approx(0.01)
    # three seasons at 10 %: P(>=2) = 3 * 0.01 * 0.9 + 0.001
    assert chance_recurring_share([0.1, 0.1, 0.1]) == pytest.approx(0.028)


def test_classify():
    scored = np.ones((4, 1, 4), bool)
    flagged = np.zeros((4, 1, 4), bool)
    flagged[0, 0, 1] = True  # once
    flagged[:2, 0, 2] = True  # 2 of 4 -> recurring, not chronic (needs >= 3)
    flagged[:3, 0, 3] = True  # 3 of 4 -> chronic
    classes, yf, ys = classify(flagged, scored)
    assert list(classes[0]) == [NEVER, ONCE, RECURRING, CHRONIC]
    scored[1:, 0, 0] = False  # scored in only one season -> no data
    assert classify(flagged, scored)[0][0, 0] == 0


def _fake_years(field, patch_years, monkeypatch, n_years=4):
    grid = grid_for(field.geometry, field.crs)
    patch = np.zeros(grid.shape, bool)
    patch[10:20, 10:20] = True  # 1 ha

    def fake_obs(f, g, start, end, cache):
        year = int(start[:4])
        obs = make_observations(grid, 8, patch=patch if year in patch_years else None, seed=year)
        for o in obs:
            o.date = o.date.replace(year=year)
        return obs

    monkeypatch.setattr(H, "_observations", fake_obs)
    return list(range(2020, 2020 + n_years))


def test_recurring_patch_is_found_and_beats_chance(square_field, tmp_path, monkeypatch):
    years = _fake_years(square_field, {2020, 2021, 2023}, monkeypatch)
    r = H.run_history(square_field, years, ("05-01", "07-01"), tmp_path)
    assert 0.8 <= r["area_ha"]["chronic"] <= 1.1  # 3 of 4 seasons
    assert r["recurring_share_observed"] > 2 * r["recurring_share_expected_by_chance"]
    z = gpd.read_file(tmp_path / "test_field" / "recurring_zones.geojson")
    top = z.sort_values("area_ha").iloc[-1]
    assert top["class"] == "chronic" and top.seasons_flagged == "2020, 2021, 2023"
    for f in ("recurrence.tif", "years_flagged.tif", "history_quicklook.png", "history_summary.md", "history.json"):
        assert (tmp_path / "test_field" / f).exists(), f


def test_one_off_patch_is_not_recurring(square_field, tmp_path, monkeypatch):
    years = _fake_years(square_field, {2022}, monkeypatch)
    r = H.run_history(square_field, years, ("05-01", "07-01"), tmp_path)
    assert r["area_ha"]["recurring"] == 0 and r["area_ha"]["chronic"] == 0
    assert 0.8 <= r["area_ha"]["flagged_once"] <= 1.1
