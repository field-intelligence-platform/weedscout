# Validation

What has been tested, how, and what the numbers say. Everything here is reproducible:

```bash
python experiments/calibrate.py                                         # 2024, ~4 min after first download
python experiments/calibrate.py --start 2023-04-01 --end 2023-07-31 --out experiments/results_2023
python experiments/select_thresholds.py experiments/results experiments/results_2023   # apply the selection rule
python experiments/reliability.py                                       # split-half + 2024 vs 2023
```

The out-of-sample check on 28 more fields is in [section 5](#5-out-of-sample-28-new-fields-across-germany).

Data: the three example field blocks near Göttingen (15.7, 22.7 and 37.5 ha), Sentinel-2 L2A, April–July of 2024 and 2023. Results tables are in [`experiments/results/`](../experiments/results) and [`experiments/results_2023/`](../experiments/results_2023).

**What this does not show:** whether flagged zones actually contain weeds or another problem. That needs a field visit. See [Ground truth](#4-ground-truth-not-yet-done) below.

---

## 1. Thresholds: chosen by rule, checked on a held-out season

The anomaly and persistence thresholds used to be judgement calls. They are now chosen by a fixed rule from a grid of 81 settings: z ∈ {−1, −1.5, −2} × deficit ∈ {5, 10, 15 %} × Watch persistence ∈ {20, 30, 40 %} × Scout persistence ∈ {50, 60, 70 %}.

**Sensitivity (can it find a real patch?).** Disc-shaped patches of 0.1, 0.25, 0.5 and 1 ha were injected into the *real* Sentinel-2 NDVI series of each field. Each patch lowers NDVI by 5–30 % on every date, at 8 random locations per field away from existing zones. That gives 480 injected seasons per year, each analysed under all 81 settings. A patch counts as found when at least half of it is classed Scout first.

**False alarms, two kinds.**
- *Chance:* each date's anomaly map is shifted by a random offset (30 times per field), so any zone that still appears can only come from one-off anomalies lining up by chance.
- *Scouting budget:* the share of each **real** field that gets flagged. This catches what the chance test cannot: harmless but persistent variation such as soil texture or tramlines. The budget is at most 15 % of any field, about what is realistic to walk.

**Rule:** maximise Scout-first recall on 0.25–1 ha patches with a 10–20 % deficit, subject to chance false alarms ≤ 1 % and every real field ≤ 15 % flagged, **in both 2024 and 2023**.

| Setting (z / deficit / Watch / Scout) | Recall 2024 | Recall 2023 | Chance false alarms | Max field flagged 2024 / 2023 | Passes rule |
|---|---|---|---|---|---|
| **−1.5 / 5 % / 40 % / 50 % (new default)** | **85 %** | **100 %** | ≤ 0.1 % | 8.1 % / 12.2 % | **yes** |
| −1.5 / 10 % / 30 % / 60 % (old hand-picked default) | 56 % | 77 % | ≤ 0.1 % | 8.5 % / 11.6 % | yes, but lower recall |
| −1.0 / 5 % / 40 % / 50 % (best on 2024 alone) | 92 %* | 100 %* | ≤ 0.3 %* | 14 % / 15.9 %* | **no**: over budget in 2023 |

\* From the first calibration pass, run before the crop-unit consensus step was added. The other two rows are from the final code.

The third row is why the held-out season matters. The best setting on 2024 alone over-flags in 2023.

**Detection limits with the new default** (share of injected patches classed Scout first):

| Patch size | 5 % deficit | 10 % | 15 % | 20 % | 30 % |
|---|---|---|---|---|---|
| 0.1 ha | 0 % | 0 % | 8 % | 0 % | 0 % |
| 0.25 ha | 4 % | 67 % | 88 % | 100 % | 100 % |
| 0.5 ha | 8 % | 67 % | 92 % | 100 % | 100 % |
| 1 ha | 0 % | 67 % | 83 % | 100 % | 100 % |

(2024; 2023 is similar or better: 100 % from a 10 % deficit and 0.25 ha upwards.)

In plain terms: **patches of about 0.25 ha (50 × 50 m) or more, at least 10–15 % weaker than the surrounding crop, are reliably found. Patches of 0.1 ha or less, or a 5 % deficit, are not.** That is a property of 10 m pixels, not something a threshold can fix.

## 2. Repeatability

### Split-half: the same zones from independent images

The season's dates are split into two interleaved halves, and each half is analysed on its own. Real zones should be found from either half. "Chance" is what randomly placed zones of the same total area would give.

| Field | Usable dates per half | Scout-first area found again in the other half | Chance |
|---|---|---|---|
| DENILI0465750023 | 7 / 7 | 73 % | 4 % |
| DENILI1765120019 | 5 / 4 | 82 % | 15 % |
| DENILI0565200005 | 7 / 7 | 100 % | 10 % |

Zones replicate far above chance. They are not artefacts of a few unlucky images.

### 2024 vs 2023: are the zones the same every year?

| Field | 2024 Scout-first area also flagged in 2023 | Chance |
|---|---|---|
| DENILI0465750023 | 0 % | 2 % |
| DENILI1765120019 | 18 % | 8 % |
| DENILI0565200005 | 15 % | 13 % |

Mostly **no**. The 2024 zones are largely specific to that season, as expected when crop and weather change. Field 1765 shows some overlap above chance, which may point to a lasting cause there. Repeated zones are worth more than one-off zones. A multi-year view is on the roadmap.

## 3. Crop units: stable across independent runs

Field blocks can contain several crops (see README). The split into crop units is now voted over 7 independent k-means runs per field. Pixels without an 80 % majority are left unscored. A membership check also removes pixels whose own seasonal curve crosses their unit's curve. Repeating the whole procedure with 5 different seed sets:

| Field | Crop units | Pixels scored differently between repeat runs |
|---|---|---|
| DENILI0465750023 | 1 | 0 % |
| DENILI1765120019 | 2 | 2 % (the border of the summer-crop strip) |
| DENILI0565200005 | 3 | 0 % |

Before the consensus step, about 5 % of field 1765 changed between runs, and a ~1 ha patch could end up scored against the wrong crop. It is now unscored in every run.

## 4. Ground truth: not yet done

None of the above says what is actually in a zone. That needs a visit, and the tool now prepares one:

```bash
weedscout-visit-kit outputs/example            # writes outputs/example/visit_kit/
```

The kit holds one GPS point per zone plus **blind control points** in Normal areas, shuffled and named P01, P02 … so the visitor cannot tell which is which. It includes `points.gpx` for a phone, a `record_sheet.csv` (weeds none / few / many, other cause, notes, photo) and a separate answer key. Afterwards:

```bash
weedscout-score-visits outputs/example/visit_kit
```

This reports, for each tier, how often a real problem (and how often weeds) was found, **compared with the control points**. Without the controls a hit rate means nothing. The next step is to visit the example zones in a growing season, with the farmer's permission.

## 5. Out-of-sample: 28 new fields across Germany

The thresholds above were chosen on three Göttingen fields. To see whether they carry over, the same experiments were run on **28 fields none of them had seen**: 4 compact arable field blocks of 10–54 ha, picked at random in each of 7 regions with different soils, climates and crops. The boundaries are in [`data/fields/germany_calibration_fields.geojson`](../data/fields/germany_calibration_fields.geojson); 12 of the 28 lie in UTM zone 33, which also exercises the automatic zone choice.

```bash
python experiments/calibrate.py --boundary data/fields/germany_calibration_fields.geojson --placements 4 --shuffles 20 --out experiments/germany_2024
python experiments/calibrate.py --boundary data/fields/germany_calibration_fields.geojson --start 2023-04-01 --end 2023-07-31 --placements 4 --shuffles 20 --out experiments/germany_2023
python experiments/regional.py --boundary data/fields/germany_calibration_fields.geojson experiments/germany_2024 experiments/germany_2023
```

**Result with the default thresholds (season April–July):**

| | Göttingen (in-sample) | 28 new fields (out-of-sample) |
|---|---|---|
| Patches found as Scout first, where a map was produced | 85 % (2024), 100 % (2023) | **79 % (2024), 67 % (2023)** |
| Fields that got a map at all | 3 of 3 | 24 of 28 (2024), 28 of 28 (2023) |
| Chance false alarms | ≤ 0.1 % | ≤ 0.3 % (1.3 % in one region) |
| Share of field flagged, average | 6 % | 7.5 % |
| Share of field flagged, worst field | 12 % | **40 %** (2024), 18 % (2023) |

So the method still does not invent zones from noise anywhere. But it finds fewer weak patches on fields it was not tuned on, and a few fields are flagged far beyond the 15 % scouting budget. **No single setting in the grid keeps every one of the 28 fields within budget in both seasons**, so a different threshold choice cannot fix this.

**Per region** (results table: [`experiments/regional_check.csv`](../experiments/regional_check.csv)):

| Region | Recall 2024 | Recall 2023 | Worst field flagged 2024 / 2023 |
|---|---|---|---|
| Uelzen heath (sandy, irrigated), Lower Saxony | 65 % | 90 % | **40 %** / 7 % |
| Fläming (sandy, dry), Brandenburg | 76 % | **27 %** | 14 % / 11 % |
| Münsterland (maize), North Rhine-Westphalia | **23 %** | 92 % | 7 % / 16 % |
| Dithmarschen marsh, Schleswig-Holstein | 76 % | 58 % | 13 % / 9 % |
| Thüringer Becken (loess), Thuringia | 73 % | 58 % | 7 % / 18 % |
| Lommatzscher Pflege (loess), Saxony | 77 % | 68 % | 11 % / 13 % |
| Güstrow (moraine), Mecklenburg-Vorpommern | 85 % | 74 % | 5 % / 16 % |

**Why the weak cases fail.** Both main failure modes come from the season window, not from the thresholds:

- **Münsterland 2024: too few dates for a late crop.** Three of the four fields had only 2 usable canopy dates between April and July. Maize forms its canopy from about June, and 2024 was cloudy. The tool correctly refused to map them, which the recall figure counts as "not found". In 2023, with more clear dates, Münsterland recall was 92 %.
- **Uelzen 2024: two crops that the window could not separate.** On the worst field (40 % flagged), a straight-edged strip is almost certainly a separately sown plot. Both parts were bare until June, and the window ended before their seasonal curves could cross. With only 6 clear canopy dates, the strip simply looked weaker than the rest and was flagged.

**What follows from this:**
1. The season window has to match the crop. April–July suits winter cereals and rapeseed; maize and sugar beet need roughly June–September. The tool now says so when it refuses to map.
2. The crop-unit split should use a longer window (spring to harvest) than the scoring window, so that late-sown plots can still be told apart. This is on the roadmap.
3. Out-of-sample recall of about 70–80 % is the honest headline figure for a new region, not the in-sample 85–100 %.

## Known limits of this validation

- **Calibrated on three fields; tested out-of-sample on 28 more in 7 regions, over two seasons.** Recall is lower out-of-sample (section 5). A new region can be checked or recalibrated with the same scripts.
- **Injected patches are idealised:** a uniform deficit on every date. Real problems vary in strength over the season, so real-world recall is likely lower than the table shows.
- **The scouting budget (15 %) and the target (0.25–1 ha, 10–20 % deficit) are design choices.** They are stated here so that anyone can change them and re-run.
