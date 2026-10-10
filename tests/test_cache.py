import pickle

import numpy as np

from weedscout import cache
from weedscout.sentinel import grid_for

from .conftest import make_observations


def _grid(field):
    return grid_for(field.geometry, field.crs)


def test_round_trip_keeps_every_value(square_field, tmp_path):
    grid = _grid(square_field)
    obs = make_observations(grid, 4, patch=(slice(5, 10), slice(5, 10)))
    obs[1].red[0, 0] = np.nan  # masked pixels must survive as NaN
    path = tmp_path / "f.npz"
    cache.save(path, obs)
    back = cache.load(path)
    assert [o.date for o in back] == [o.date for o in obs]
    assert [o.item_ids for o in back] == [o.item_ids for o in obs]
    for a, b in zip(obs, back):
        np.testing.assert_array_equal(a.red, b.red)
        np.testing.assert_array_equal(a.nir, b.nir)
        np.testing.assert_array_equal(a.scl, b.scl)
        assert b.scl.dtype == np.uint8 and b.red.dtype == np.float32


def test_file_holds_no_pickled_objects(square_field, tmp_path):
    path = tmp_path / "f.npz"
    cache.save(path, make_observations(_grid(square_field), 2))
    with np.load(path, allow_pickle=False) as z:  # raises if any member needed pickle
        assert sorted(z.files) == ["meta", "nir", "red", "scl"]


def test_empty_season_round_trips(tmp_path):
    path = tmp_path / "empty.npz"
    cache.save(path, [])
    assert cache.load(path) == []


def test_damaged_or_foreign_file_is_ignored(tmp_path):
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not a numpy archive")
    assert cache.load(bad) is None
    assert cache.load(tmp_path / "missing.npz") is None


def test_old_pickle_cache_is_never_loaded(square_field, tmp_path, monkeypatch):
    grid = _grid(square_field)
    calls = []

    class Boom:
        def __reduce__(self):  # would run on unpickling
            calls.append("unpickled")
            return (print, ("pickle was loaded",))

    old = tmp_path / f"{square_field.field_id}_2024-03-01_2024-10-31.pkl"
    old.write_bytes(pickle.dumps(Boom()))
    calls.clear()
    fresh = make_observations(grid, 3)
    monkeypatch.setattr(cache, "search", lambda geom, start, end: ["item"])
    monkeypatch.setattr(cache, "load_observations", lambda items, g: fresh)
    got = cache.observations(square_field, grid, "2024-03-01", "2024-10-31", tmp_path)
    assert got is fresh and calls == []
    assert cache.cache_path(tmp_path, square_field.field_id, "2024-03-01", "2024-10-31").exists()


def test_second_call_uses_the_cache(square_field, tmp_path, monkeypatch):
    grid = _grid(square_field)
    downloads = []
    monkeypatch.setattr(cache, "search", lambda geom, start, end: ["item"])
    monkeypatch.setattr(cache, "load_observations", lambda items, g: downloads.append(1) or make_observations(g, 3))
    first = cache.observations(square_field, grid, "2024-03-01", "2024-10-31", tmp_path)
    second = cache.observations(square_field, grid, "2024-03-01", "2024-10-31", tmp_path)
    assert len(downloads) == 1
    assert [o.date for o in second] == [o.date for o in first]


def test_cache_for_a_different_grid_is_not_reused(square_field, tmp_path, monkeypatch):
    grid = _grid(square_field)
    path = cache.cache_path(tmp_path, square_field.field_id, "2024-03-01", "2024-10-31")
    small = make_observations(grid, 2)
    for o in small:
        o.red, o.nir, o.scl = o.red[:3, :3], o.nir[:3, :3], o.scl[:3, :3]
    cache.save(path, small)
    monkeypatch.setattr(cache, "search", lambda geom, start, end: ["item"])
    monkeypatch.setattr(cache, "load_observations", lambda items, g: make_observations(g, 3))
    got = cache.observations(square_field, grid, "2024-03-01", "2024-10-31", tmp_path)
    assert got[0].red.shape == grid.shape
