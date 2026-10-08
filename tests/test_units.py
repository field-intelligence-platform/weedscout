import numpy as np

from weedscout.units import UNUSUAL, UnitSettings, crop_units, curves_cross, interior, real_units

CEREAL = [0.8, 0.8, 0.8, 0.3, 0.2]
MAIZE = [0.2, 0.2, 0.5, 0.9, 0.9]
SMALL_UNITS = UnitSettings(min_unit_ha=0.5)


def _two_crops(patch=None, patch_curve=None):
    """30 x 30 px: west half cereal, east half maize, optional patch with its own curve."""
    dates = []
    for i, (c, m) in enumerate(zip(CEREAL, MAIZE)):
        v = np.full((30, 30), c)
        v[:, 15:] = m
        if patch is not None:
            v[patch] = patch_curve[i]
        dates.append(v + np.random.default_rng(0).normal(0, 0.01, v.shape))
    return dates


def test_crossing_curves_mean_different_crops():
    cereal = np.array([0.7, 0.8, 0.85, 0.6, 0.3, 0.22])
    maize = np.array([0.2, 0.2, 0.5, 0.85, 0.9, 0.9])
    weak_cereal = cereal - 0.2
    assert curves_cross(cereal, maize, UnitSettings())
    assert not curves_cross(cereal, weak_cereal, UnitSettings())


def test_single_noisy_crossing_date_is_not_enough():
    a = np.array([0.8, 0.8, 0.8, 0.8])
    b = np.array([0.6, 0.6, 0.6, 0.97])  # only one date where b leads
    assert not curves_cross(a, b, UnitSettings())


def test_too_few_dates_gives_one_unit():
    mask = np.ones((10, 10), bool)
    units, curves = crop_units([np.full((10, 10), 0.5)] * 3, mask, 0.01)
    assert units.max() == 1 and curves == []


def test_two_crops_give_two_units():
    units, curves = crop_units(_two_crops(), np.ones((30, 30), bool), 0.01, SMALL_UNITS)
    assert real_units(units) == [1, 2] and len(curves) == 2
    assert units[10, 5] != units[10, 25]


def test_speck_of_other_crop_is_not_scored_against_its_neighbour():
    speck = (slice(2, 4), slice(2, 4))  # 4 px (0.04 ha) maize-like speck inside the cereal
    units, _ = crop_units(_two_crops(speck, MAIZE), np.ones((30, 30), bool), 0.01, SMALL_UNITS)
    assert (units[speck] == UNUSUAL).all()
    assert units[10, 5] != UNUSUAL


def test_detached_piece_of_a_crop_stays_with_that_crop():
    piece = (slice(2, 6), slice(2, 6))  # 16 px (0.16 ha) of maize cut off inside the cereal
    units, _ = crop_units(_two_crops(piece, MAIZE), np.ones((30, 30), bool), 0.01, SMALL_UNITS)
    assert (units[piece] == units[10, 25]).all()


def test_small_patch_unlike_any_crop_is_unusual():
    cereal = [0.8, 0.8, 0.8, 0.8, 0.3, 0.2, 0.2, 0.2]
    maize = [0.2, 0.2, 0.2, 0.5, 0.9, 0.9, 0.9, 0.9]
    odd_curve = [0.8, 0.8, 0.2, 0.2, 0.2, 0.2, 0.8, 0.8]  # green, bare, re-greening after harvest
    odd = (slice(2, 6), slice(2, 6))
    dates = []
    for c, m, o in zip(cereal, maize, odd_curve):
        v = np.full((30, 30), c)
        v[:, 15:] = m
        v[odd] = o
        dates.append(v + np.random.default_rng(0).normal(0, 0.01, v.shape))
    units, _ = crop_units(dates, np.ones((30, 30), bool), 0.01, SMALL_UNITS)
    assert (units[odd] == UNUSUAL).all()
    assert real_units(units) == [1, 2]


def test_interior_drops_unit_border_pixels():
    units = np.ones((10, 10), "uint8")
    units[:, 5:] = 2
    inner = interior(units, 1)
    assert inner[:, :4].all() and not inner[:, 4].any()
