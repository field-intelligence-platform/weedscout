# Validation

What has been tested, how, and what the numbers say. All results below use the default analysis: the **whole growing season** (1 March – 31 October), with each crop scored in its own growing period. Everything is reproducible:

```bash
# Calibration fields (3 field blocks near Göttingen)
python experiments/calibrate.py --start 2024-03-01 --end 2024-10-31 --out experiments/fullseason_goettingen_2024
python experiments/calibrate.py --start 2023-03-01 --end 2023-10-31 --out experiments/fullseason_goettingen_2023
python experiments/select_thresholds.py experiments/fullseason_goettingen_2024 experiments/fullseason_goettingen_2023
python experiments/reliability.py                                   # split-half + 2024 vs 2023

# Out-of-sample fields (28 field blocks in 7 German regions)
B=data/fields/germany_calibration_fields.geojson
python experiments/calibrate.py --boundary $B --start 2024-03-01 --end 2024-10-31 --placements 4 --shuffles 20 --out experiments/fullseason_germany_2024
python experiments/calibrate.py --boundary $B --start 2023-03-01 --end 2023-10-31 --placements 4 --shuffles 20 --out experiments/fullseason_germany_2023
python experiments/regional.py --boundary $B experiments/fullseason_germany_2024 experiments/fullseason_germany_2023
```

Sentinel-2 series are cached in `outputs/cache` after the first download. Summary tables are committed under [`experiments/`](../experiments). The large raw tables are not committed, but re-running the commands regenerates them.

**What this does not show:** whether flagged zones actually contain weeds or another problem. That needs a field visit (section 6).

---

## 1. Thresholds: chosen by rule, checked on new data

The anomaly and persistence thresholds are chosen by a fixed rule from a grid of 81 settings: z ∈ {−1, −1.5, −2} × deficit ∈ {5, 10, 15 %} × Watch persistence ∈ {20, 30, 40 %} × Scout persistence ∈ {50, 60, 70 %}.

- **Sensitivity:** disc-shaped patches of 0.1–1 ha are injected into the *real* Sentinel-2 NDVI series of each field, lowering NDVI by 5–30 % on every date at random clean locations. A patch counts as found when at least half of it is classed Scout first.
- **Chance false alarms:** each date's anomaly map is shifted by a random offset, so any zone that still appears can only come from one-off anomalies lining up by chance.
- **Scouting budget:** the share of each **real** field that gets flagged. This catches harmless but persistent variation (soil, tramlines), which the chance test cannot.
- **Rule:** the highest Scout-first recall on 0.25–1 ha patches with a 10–20 % deficit, subject to chance false alarms ≤ 1 % and every field ≤ 15 % flagged, in every season.

**Default: z ≤ −1.5, deficit ≥ 5 %, Watch ≥ 40 %, Scout first ≥ 50 %.**

| On the 3 calibration fields | Recall 2024 / 2023 | Chance false alarms | Worst field flagged 2024 / 2023 |
|---|---|---|---|
| **Default (−1.5 / 5 % / 40 % / 50 %)** | **92 % / 100 %** | 0 % | 4.1 % / 7.5 % |
| −1.0 / 5 % / 40 % / 50 % (what the rule picks on these 3 fields alone) | 99.5 % / 100 % | 0 % | 7.9 % / 7.9 % |

On the three calibration fields, the rule now prefers the more sensitive z ≤ −1.0. **It was not adopted**, because the out-of-sample test (section 4) shows it flags more of every new field and worsens the worst field (26 % vs 17 % in 2023). This is the same kind of over-fitting the held-out season caught in the first calibration round.

**Detection limits with the default** (calibration fields, share of injected patches classed Scout first):

| Patch size | 5 % deficit | 10 % | 15 % | 20 % | 30 % |
|---|---|---|---|---|---|
| 0.1 ha | 0 % | 0–4 % | 4 % | 4–8 % | 8–12 % |
| 0.25 ha | 0–46 % | 88–100 % | 96–100 % | 100 % | 100 % |
| 0.5 ha | 4–50 % | 83–100 % | 96–100 % | 100 % | 100 % |
| 1 ha | 4–33 % | 67–100 % | 96–100 % | 100 % | 100 % |

(Ranges cover 2024 and 2023.) **Patches of about 0.25 ha (50 × 50 m) or more, at least 10–15 % weaker than the rest of their crop, are reliably found. Patches of 0.1 ha are not.** That is a property of 10 m pixels.

## 2. Repeatability

**Split-half:** the season's dates are split into two interleaved halves, and each half is analysed on its own.

| Field | Usable dates per half | Scout-first area found again from the other half | Chance |
|---|---|---|---|
| DENILI0465750023 | 7 / 7 | 71 % | 3 % |
| DENILI1765120019 | 10 / 10 | 78 % | 15 % |
| DENILI0565200005 | 10 / 11 | 100 % | 3 % |

Zones replicate far above chance from independent images.

**Year to year:** 2024 zones were not flagged again in 2023 on field 0465 (0 %), and could not be compared on field 1765, where the 2024 zone fell outside the area scored in both years. On field 0565, 53 % of the 2024 Scout-first area was flagged again in 2023 (chance 8 %). See section 5 for the full 2019–2024 picture.

## 3. Crop units: stable across independent runs

The split into crop units is voted over 7 independent k-means runs per field. Pixels without an 80 % majority are left unscored, and a membership check removes pixels whose own seasonal curve crosses their unit's curve. Repeating the whole procedure with 5 different seed sets changed the scoring of 0 %, 2 % and 0 % of pixels on the three fields.

## 4. Out-of-sample: 28 new fields across Germany

The same experiments were run on **28 fields the thresholds had never seen**: 4 compact arable field blocks of 10–54 ha, picked at random in each of 7 regions with different soils, climates and crops ([`data/fields/germany_calibration_fields.geojson`](../data/fields/germany_calibration_fields.geojson)). 12 of them lie in UTM zone 33.

| | Calibration fields | **28 new fields** |
|---|---|---|
| Patches found as Scout first | 92 % / 100 % | **81 % / 79 %** (2024 / 2023) |
| Fields that got a map | 3 / 3 | 27 / 28 (2024), 28 / 28 (2023) |
| Chance false alarms | 0 % | ≤ 0.1 % |
| Share of field flagged, average | 3–5 % | 6.6–6.7 % |
| Share of field flagged, worst field | 7.5 % | **38 %** (2024), 17 % (2023) |

**Per region** ([`experiments/regional_check_fullseason.csv`](../experiments/regional_check_fullseason.csv)):

| Region | Recall 2024 / 2023 | Worst field flagged 2024 / 2023 |
|---|---|---|
| Dithmarschen marsh, Schleswig-Holstein | 97 % / 100 % | 12 % / 11 % |
| Thüringer Becken (loess), Thuringia | 98 % / 72 % | 7 % / 14 % |
| Güstrow (moraine), Mecklenburg-Vorpommern | 96 % / 76 % | 13 % / 15 % |
| Lommatzscher Pflege (loess), Saxony | 87 % / 76 % | 9 % / 14 % |
| Münsterland (maize), North Rhine-Westphalia | 73 % / 91 % | 8 % / 17 % |
| Uelzen heath (sandy, irrigated), Lower Saxony | 60 % / 98 % | **38 %** / 8 % |
| Fläming (sandy, dry), Brandenburg | **56 % / 38 %** | 11 % / 7 % |

The method does not invent zones from noise anywhere, and it works well in most regions. Two weak spots remain, and both have a physical explanation:

- **Fläming: naturally patchy crops hide weaker problems.** On dry sandy soil the crop's own NDVI varies about twice as much as elsewhere: a typical spread of 10 % of the field median, against 3–5 % in the other regions. A weak spot only stands out if it is weaker than that natural patchiness. There, problems with a 30 % deficit were still found 73–94 % of the time, but 10–15 % deficits mostly were not. **Every summary now states, per crop, how weak a problem can be and still be told apart** (e.g. "problems weaker than about 12 % … cannot be told apart from its natural patchiness").
- **Uelzen 2024: a strip sown or emerging about three weeks later.** On the worst field (38 % flagged), a straight-edged 5.7 ha strip follows the same crop curve as the rest, only later: a little greener in April, far lower in June, identical from July to harvest. Satellite data cannot tell a deliberately later sowing from poor emergence. **Zones covering 20 % or more of their crop are now marked `likely_management_difference`**, and the summary asks the user to check the field records before scouting them.

## 5. Multi-year view (2019–2024)

`weedscout-history` analyses each season on its own and compares the recurring area with what independent seasons would produce by chance.

| Field | Recurring + chronic | Expected by chance |
|---|---|---|
| DENILI0465750023 | 0.0 % | 0.1 % |
| DENILI1765120019 | 5.5 % | 4.5 % |
| DENILI0565200005 | 3.0 % | 2.7 % |

On these three fields, zones mostly change from season to season, roughly as chance would predict. An earlier run with an April–July window suggested a "chronic" headland zone on field 0465 at 2.7× chance. **It did not survive the switch to whole-season analysis, so it should not be treated as a finding.** Recurrence is worth checking per field, but none was demonstrated here.

## 6. Ground truth: not yet done

None of the above says what is actually in a zone. That needs a visit, and the tool prepares one:

```bash
weedscout-visit-kit outputs/example            # writes outputs/example/visit_kit/
weedscout-score-visits outputs/example/visit_kit
```

The kit holds one GPS point per zone plus **blind control points** in Normal areas, shuffled and named P01, P02 …, with a record sheet and a separate answer key. Scoring reports how often each tier had a real problem (and how often weeds) **compared with the controls**.

## How we got here

The first calibration used an April–July window. Out-of-sample it found 67–79 % of patches and flagged one field at 40 %. The diagnosis was that the window did not suit late crops: maize fields had as few as 2 usable dates (Münsterland 2024, 23 % recall), and later-sown plots could not be separated. Switching to whole-season analysis with per-crop growing periods raised out-of-sample recall to 79–81 % with less flagging on average. Those first-round tables are kept for reference in `experiments/results*`, `experiments/germany_*` and `experiments/regional_check_aprjul.csv`.

## Known limits

What the tool cannot do, and where its results need care. The README's *Before you use the map* gives the practical
version.

- **Not checked in the field yet.** All tests use patches planted into real satellite data. Whether real zones are
  weeds or another problem is unknown until zones are visited (section 6).
- **The cause is unknown.** The map says *where*, never *why*. On the example fields most Scout-first zones touch the
  field edge, where headland compaction, hedge shading and turning overlaps are common.
- **Detection floor of about 0.25 ha.** Patches of 0.1 ha or less are not found reliably (section 1). Planted test
  patches were equally weak on every date; real problems that vary in strength will be found less often.
- **Patchy crops hide weaker problems.** On naturally variable fields, such as dry sandy soils, only clearly weak spots
  stand out (section 4: the Fläming fields). Each summary states this limit per crop.
- **Weeds are only visible when they change the canopy at 10 m scale**, for example dense patches of grass weeds or
  thistles over many square metres. Scattered weeds under a closed canopy are invisible.
- **Somewhat weaker on new fields than on the calibration fields:** 79–81 % instead of 92–100 % of planted patches
  (section 4). Checking or recalibrating for a new region takes one command per season.
- **A strip sown later looks like poor emergence.** It follows the same crop curve, only later, and can be flagged as a
  whole (one test field: 38 % flagged). Such zones are marked `likely_management_difference`.
- **Field blocks are not always single fields.** The example boundaries are official field blocks, which can hold
  several farmers' plots. Crops with different seasonal curves are separated; two plots of the same crop sown at the
  same time are not.
- **Some ground is left unscored:** crop-unit borders, pixels whose crop is uncertain, and unusual-pattern patches.
  They appear blank or purple on the map, never as Normal.
- **Cloudy seasons give fewer dates.** Persistence over 6 dates is weaker evidence than over 20, which is why each zone
  reports its number of flagged dates. With fewer than 3 usable dates for a crop there is no map.

## Known limits of this validation

- **Calibrated on three fields, tested on 28 more in 7 regions, over two seasons.** Elsewhere, check or recalibrate with the scripts above.
- **Injected patches are idealised:** a uniform deficit on every date. Real problems vary in strength over the season, so real-world recall is likely lower.
- **The scouting budget (15 %) and the target (0.25–1 ha, 10–20 % deficit) are design choices.** They are stated so that anyone can change them and re-run.
