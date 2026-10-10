# Security policy

## Supported versions

Security fixes go into the newest release only. Please check that a problem still exists in the
[latest release](https://github.com/field-intelligence-platform/Precision-Weed-Detection-and-Targeted-Spraying/releases/latest)
before reporting it.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report them privately through GitHub: open the repo's **Security** tab → **Report a vulnerability**. Only the
maintainers can see the report. Please include:

- what the problem is and what an attacker could do with it,
- the weedscout version, your operating system and Python version,
- the steps or the file needed to reproduce it (an anonymised or synthetic boundary file is enough; never send real
  farm data).

We will confirm the report within a week, keep you updated, and credit you in the release notes if you wish.

## What weedscout does with your input

This helps to judge what is in scope:

- weedscout runs **locally** on your computer. It has no server, no accounts and no telemetry.
- It **reads** the boundary file you pass with `--boundary` (Shapefile, zipped Shapefile, GeoJSON, KML/KMZ, GPX,
  GeoPackage) through GDAL/pyogrio. Zipped Shapefiles are read in place through GDAL's virtual file system and are
  **not unpacked to disk**.
- It **downloads** public Sentinel-2 imagery from the Microsoft Planetary Computer STAC API over HTTPS. No API key or
  credentials are used or stored.
- It **writes** results only into the folder given with `--out`. The multi-year view (`--cache`, default
  `outputs/cache/`) and the validation experiments also cache downloaded imagery there, as Python pickle files.
  **Only use cache files that weedscout created on your own computer**: loading a pickle file from someone else can
  run code. (Replacing pickle with a safe format is planned.)

In scope, for example: a crafted input file that makes weedscout read or write files outside these places, run code,
or hang/crash in a way a normal malformed file should not. Out of scope: wrong or misleading scouting results (please
open a normal issue), and problems in the Planetary Computer or in third-party libraries (please report those
upstream).
