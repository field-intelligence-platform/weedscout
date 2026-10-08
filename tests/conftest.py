from datetime import date, timedelta

import numpy as np
import pytest
from shapely.geometry import box

from weedscout.boundary import Field, utm_crs_for
from weedscout.sentinel import Observation


@pytest.fixture
def square_field():
    """A 400 m x 400 m (16 ha) field near Goettingen, in UTM 32N."""
    crs = utm_crs_for(9.93, 51.53)
    x0, y0 = 565_000.0, 5_710_000.0
    return Field("test_field", box(x0, y0, x0 + 400, y0 + 400), crs, 16.0)


def make_observations(grid, n_dates, base_ndvi=0.75, patch=None, patch_ndvi=0.45, noise=0.02,
                      patch_dates=None, seed=0):
    """Synthetic clear observations: uniform canopy with an optional low-vigour patch."""
    rng = np.random.default_rng(seed)
    obs = []
    for i in range(n_dates):
        target = np.full(grid.shape, base_ndvi) + rng.normal(0, noise, grid.shape)
        if patch is not None and (patch_dates is None or i in patch_dates):
            target[patch] = patch_ndvi
        red = np.full(grid.shape, 0.05, dtype="float32")
        nir = (red * (1 + target) / (1 - target)).astype("float32")
        scl = np.full(grid.shape, 4, dtype="uint8")
        obs.append(Observation(date(2024, 5, 1) + timedelta(days=5 * i), [f"item{i}"], red, nir, scl))
    return obs
