from datetime import date

import numpy as np
from pyproj import CRS
from shapely.geometry import box

from weedscout.anomaly import ndvi
from weedscout.sentinel import boa_offset, clear_mask, grid_for, to_reflectance


def test_offset_applied_from_baseline_04():
    assert boa_offset({"s2:processing_baseline": "05.10"}, date(2023, 8, 28)) == -1000
    assert boa_offset({"s2:processing_baseline": "04.00"}, date(2022, 2, 1)) == -1000
    assert boa_offset({"s2:processing_baseline": "03.01"}, date(2021, 6, 1)) == 0


def test_offset_inferred_from_date_when_baseline_missing():
    assert boa_offset({}, date(2024, 5, 1)) == -1000
    assert boa_offset({}, date(2020, 5, 1)) == 0


def test_offset_changes_ndvi_as_expected():
    """Healthy canopy: red 0.05, NIR 0.35 -> true NDVI 0.75. v0 computed 0.50 from raw DN."""
    red_dn, nir_dn = np.array([1500]), np.array([4500])  # includes the +1000 offset
    raw = ndvi(red_dn.astype(float), nir_dn.astype(float))
    fixed = ndvi(to_reflectance(red_dn, -1000), to_reflectance(nir_dn, -1000))
    assert np.isclose(raw[0], 0.5)
    assert np.isclose(fixed[0], 0.75)


def test_dn_zero_is_nodata():
    refl = to_reflectance(np.array([0, 1000, 3000]), -1000)
    assert np.isnan(refl[0]) and refl[1] == 0 and np.isclose(refl[2], 0.2)


def test_clear_mask_drops_cloud_snow_and_cloud_edges():
    scl = np.full((9, 9), 4, dtype="uint8")
    scl[4, 4] = 9  # high-probability cloud
    scl[0, 8] = 11  # snow
    m = clear_mask(scl)
    assert not m[4, 4] and not m[4, 6] and not m[2, 4]  # cloud plus 2 px buffer
    assert m[4, 7] and m[8, 0]
    assert not m[0, 8]


def test_grid_is_snapped_and_metric():
    g = grid_for(box(565_003, 5_710_007, 565_397, 5_710_396), CRS.from_epsg(32632))
    assert g.res == 10
    assert g.transform.c % 10 == 0 and g.transform.f % 10 == 0
    assert g.width == 46 and g.height == 46
