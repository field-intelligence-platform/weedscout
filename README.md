# Precision Weed Scouting — where to look first, from Sentinel-2

[![tests](https://github.com/gowthamuppalapati/Precision-Weed-Detection-and-Targeted-Spraying/actions/workflows/tests.yml/badge.svg)](https://github.com/gowthamuppalapati/Precision-Weed-Detection-and-Targeted-Spraying/actions/workflows/tests.yml)

**Version 1.0.0** · Python ≥ 3.10 · free data only (Sentinel-2 via Microsoft Planetary Computer) · status: working, not yet ground-truthed

Give it a field-boundary file and a season. It returns a map of the zones that **underperformed the rest of their own crop on most clear-sky dates**, so a farmer, agronomist or drone knows where to walk first.

It is a **scouting map, not a weed detector.** Sentinel-2 pixels are 10 m wide, so individual weeds and most weed patches are not visible from orbit. Low vigour can come from weeds, but equally from waterlogging, compaction, nutrient deficiency, pests or poor emergence. Every output says this, and each zone carries the evidence behind it ("flagged on 8 of 9 clear dates"). Actual weed detection is the job of v2, a segmentation model on drone imagery (see [Roadmap](#roadmap)).

![Scouting map for a 22.7 ha field block near Göttingen, 2024](outputs/example/DENILI1765120019/quicklook.png)

*Field block DENILI1765120019 near Göttingen, April–July 2024. The block holds two crops (U1 winter cereal, U2 summer crop). Each crop is compared only with itself. Red/orange are persistent low-vigour zones inside a crop; purple is a patch whose seasonal curve matches neither crop, so it is shown but not scored.*

## Example results (3 official field blocks near Göttingen, 2024 season)

| Field block | Area | Crop units found | Usable dates | Scout first | Watch | Unusual pattern |
|---|---|---|---|---|---|---|
| [DENILI0465750023](outputs/example/DENILI0465750023/summary.md) | 15.7 ha | 1 | 14 | 0 ha | 0.19 ha | – |
| [DENILI1765120019](outputs/example/DENILI1765120019/summary.md) | 22.7 ha | 2 | 9 / 6 | 1.21 ha (3 zones) | 0.61 ha | 0.80 ha |
| [DENILI0565200005](outputs/example/DENILI0565200005/summary.md) | 37.5 ha | 3 | 10 / 14 / 12 | 0.73 ha (1 zone) | 0.29 ha | – |

A uniform field returns almost nothing, which is the correct answer for a field with no problem. The flagged share (Watch + Scout first) is 1.3 %, 3.2 % and 10.4 % of the analysed area. v0 flagged 99.8 %.

**Not yet validated on the ground.** These zones have not been visited. Until they are, treat the tiers as a prioritised list of places to check, not as findings.

Maps for the other two fields: [DENILI0565200005](outputs/example/DENILI0565200005/quicklook.png) (three crop units, including a separately sown plot) · [DENILI0465750023](outputs/example/DENILI0465750023/quicklook.png) (uniform field, almost nothing flagged).

## Quick start

```bash
git clone https://github.com/gowthamuppalapati/Precision-Weed-Detection-and-Targeted-Spraying.git
cd Precision-Weed-Detection-and-Targeted-Spraying
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

weedscout --boundary data/fields/goettingen_example_fields.geojson \
          --start 2024-04-01 --end 2024-07-31 --out outputs/my_run
pytest                                                   # offline tests, no network needed; CI runs them on Linux, Windows and macOS, Python 3.10–3.13
```

No API key is needed: imagery comes from the free [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/) STAC API. A run over three fields and one season takes about a minute. The command above reproduces the committed example in [`outputs/example/`](outputs/example/).

### Command-line options

| Option | Default | Meaning |
|---|---|---|
| `--boundary` | required | boundary file; every feature is one field |
| `--start`, `--end` | required | season window, `YYYY-MM-DD`. Include some bare-soil and post-harvest dates: they are what separates crops into units |
| `--out` | `outputs` | output folder; one sub-folder per field |
| `--id-column` | auto | attribute holding the field id (auto: `field_id`, `id`, `flik`, `name`) |
| `--min-zone-ha` | `0.1` | smallest zone that is reported |
| `--edge-buffer-m` | `10` | strip along the field edge left out of the analysis |
| `--max-tile-cloud` | `80` | loose pre-filter on whole-tile cloud cover; the field itself is checked pixel by pixel |
| `-v` | off | verbose logging |

Exit code `0` = all fields mapped, `1` = at least one field had too few usable dates, `2` = the boundary file could not be used.

### Project structure

```
src/weedscout/
  boundary.py   read and validate boundary files, choose the UTM zone
  sentinel.py   Sentinel-2 search, reflectance conversion, cloud masking, 10 m field grid
  units.py      split a boundary into crop units from seasonal NDVI curves
  anomaly.py    per-date field-relative anomalies, persistence, tiers, all thresholds
  zones.py      clean tiers, vectorise zones with per-zone statistics
  export.py     COG / GeoJSON / Shapefile / PNG / summary writers
  pipeline.py   one field from boundary to outputs
  cli.py        the `weedscout` command
tests/          offline tests on synthetic fields (no network)
data/fields/    example boundaries (official Lower Saxony field blocks)
outputs/example/  committed example run, 2024 season
```

### Input: the boundary files farmers already have

| Format | Notes |
|---|---|
| Shapefile (`.shp` or zipped `.zip`) | needs its `.prj` file; exports from farm-management software work as-is |
| GeoJSON, GeoPackage | any CRS |
| KML | e.g. drawn in Google Earth |
| GPX | a track or route walked around the field edge is closed into a polygon |

Every feature becomes one field. The id comes from `field_id`, `id`, `flik` or `name` (or `--id-column`). Boundaries are repaired if self-intersecting. Anything over 1,000 ha or under 1 ha is rejected with a plain explanation, because neither can be analysed as one field at 10 m resolution.

### Output, per field (`outputs/<run>/<field_id>/`)

| File | What it is | Opens in |
|---|---|---|
| `quicklook.png` | the map above | anything |
| `summary.md` | plain-language result, crop units, and every date with why it was or wasn't used | any text viewer, GitHub |
| `scouting_zones.geojson` | zone polygons with tier, area, persistence, NDVI deficit, `at_field_edge` | QGIS, Google Earth, web maps |
| `scouting_zones_shapefile.zip` | the same zones as a Shapefile | farm-management and sprayer task-controller software |
| `scouting_tiers.tif` | tier raster (Cloud-Optimized GeoTIFF; 0 = no data, 1 normal, 2 watch, 3 scout first, 4 unusual) | QGIS, any GIS |
| `persistence_pct.tif` | % of usable dates each pixel was flagged | QGIS |
| `season_median_ndvi.tif` | median NDVI over usable dates | QGIS |
| `crop_units.tif` | crop unit per pixel (255 = unusual pattern) | QGIS |
| `report.json` | everything above plus settings, Sentinel-2 item ids and per-unit NDVI curves, for reproducibility | – |

## Method

1. **Read the boundary** and project it to the field's own UTM zone, taken from the field's location rather than hardcoded.
2. **Load every Sentinel-2 L2A date** in the season onto a 10 m grid aligned with the Sentinel-2 tiles.
   - Convert DN to reflectance **with the −1000 BOA offset** used since processing baseline 04.00 (January 2022).
   - Mask each date with the Scene Classification Layer, keeping only vegetation and bare soil, and grow cloud and shadow masks by 20 m.
   - Merge overlapping tiles from the same day.
   - Drop a 10 m strip along the field edge to remove pixels mixed with roads and hedges.
3. **Split the boundary into crop units.** Official field blocks, and many farm boundary files, can contain more than one crop. Pixels are clustered on their NDVI curve over every clear date of the season (k-means, k = 5, best of 10 runs). Clusters are then merged unless their curves **cross**, meaning each one is at least 0.15 NDVI greener than the other on at least 2 dates. Two different crops cross because they green up and are harvested at different times. A stressed patch of the same crop follows the same curve, only lower. Patches smaller than 1 ha join a neighbouring unit only if their curve matches it. Otherwise they are marked **unusual pattern** and not scored.
4. **Find anomalies within each unit, date by date.** A date is used for a unit only if at least 80 % of the unit is clear and the unit's median NDVI is at least 0.4 (crop canopy present; bare and harvested dates are skipped with the reason logged). A pixel is flagged on a date when it is both
   - a robust outlier: z ≤ −1.5, where z = (NDVI − unit median) / (1.4826 × MAD), and
   - agronomically meaningful: at least 10 % below the unit median. This stops a very uniform field from turning sensor noise into zones.
5. **Persistence is the confidence.** Each pixel's share of usable dates on which it was flagged gives the tier: ≥ 60 % **Scout first**, ≥ 30 % **Watch**, otherwise **Normal**. A unit with fewer than 3 usable dates gets **no map at all**, with an explanation. A single date cannot separate a persistent problem from a passing one.
6. **Zones:** patches under 0.1 ha are removed, and the rest are vectorised. Statistics are read from the same pixel grid the polygons come from, so they cannot drift onto the wrong CRS.

All thresholds are in [`Settings`](src/weedscout/anomaly.py) and [`UnitSettings`](src/weedscout/units.py) and are recorded in every `report.json`.

## Limitations — read before using the map

- **Not ground-truthed.** Nothing here has been checked in the field yet. That is the next step (see Roadmap).
- **Cause is unknown.** The map says *where*, never *why*. Weeds are one possible cause among many.
- **Weeds are only visible when they change the canopy at 10 m scale**, for example dense patches of grass weeds or thistles over many square metres. Scattered weeds under a closed canopy are invisible.
- **Field blocks ≠ fields.** The example boundaries are official Lower Saxony *Feldblöcke*, which can hold several farmers' plots. The crop-unit step handles most of this, but a plot smaller than 1 ha or with a crop calendar similar to its neighbour's cannot be separated.
- **Crop-unit borders are uncertain at roughly the 1 ha scale.** In field 1765 one ~1 ha patch is "unusual" or part of the summer crop depending on the k-means initialisation; in neither case is it flagged for scouting. Results are reproducible because the seed is fixed.
- **Cloudy seasons give fewer dates.** In 2024 only 14–16 of 27 Sentinel-2 dates were clear over each field, and fewer still had a crop canopy (6–14 per unit). Persistence over 5–6 dates (unit U2 above) is weaker evidence than over 14, which is why `flagged_dates` is reported per zone.
- **Edge zones** (`at_field_edge = true`) often reflect headland compaction, shading by hedges or turning overlaps rather than in-crop problems.

## Roadmap

- **Ground-truth visit** to the example zones next season, recording what was actually there. This turns "suspected" into a measured hit rate.
- **v2 — weed detection on drone imagery:** a U-Net / DeepLabv3 segmentation model trained on WeedMap / CropAndWeed. The scouting map tells the drone where to fly.
- **Spray-priority dashboard:** FastAPI + MapLibre front-end serving these outputs per field.

## Data and licences

- Sentinel-2 L2A: Copernicus Sentinel data (2024), via Microsoft Planetary Computer.
- Example field boundaries: Data: © ML/SLA Niedersachsen (2024), [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0), Daten bearbeitet. Via [fiboa / Source Cooperative](https://source.coop/fiboa/de-nds).

## Author

**Gowtham Uppalapati** — M.Sc. Sustainable International Agriculture, University of Göttingen & University of Kassel.
