# Installing weedscout on your computer

Every step to get weedscout running on your own computer, from an empty machine to your first scouting map.
Written for Windows first, with the macOS/Linux differences next to each step.

**Time:** about 15–20 minutes the first time. **Disk space:** about 1.5 GB (Python packages; the multi-year view
and the validation experiments also cache satellite data, a few hundred MB). **Internet:** needed for installing and for every new analysis.

Contents:
[1. What you need](#1-what-you-need) ·
[2. Get access to the repo](#2-get-access-to-the-repo) ·
[3. Install the tools](#3-install-the-tools) ·
[4. Download the code](#4-download-the-code) ·
[5. Create a Python environment](#5-create-a-python-environment) ·
[6. Install weedscout](#6-install-weedscout) ·
[7. Check that it works](#7-check-that-it-works) ·
[8. Your first scouting map](#8-your-first-scouting-map) ·
[9. Look at the results](#9-look-at-the-results) ·
[10. Every day after that](#10-every-day-after-that) ·
[11. Troubleshooting](#11-troubleshooting) ·
[12. Remove everything](#12-remove-everything)

---

## 1. What you need

| Tool | Version | What for |
|---|---|---|
| A GitHub account | with access to the organisation `field-intelligence-platform` | the repo is private |
| Git | any recent version | downloading the code and sending changes |
| Python | **3.10, 3.11, 3.12 or 3.13** (3.12 recommended) | running weedscout |
| QGIS | optional, any recent LTR | looking at the maps weedscout makes |
| VS Code | optional | editing code |

> Python 3.14 is too new: some geodata packages (rasterio, pyogrio) may not have ready-made installers for it yet.
> Use 3.12 if you are unsure.

## 2. Get access to the repo

1. Make sure you have a GitHub account (https://github.com/signup).
2. Send your GitHub username to an organisation owner and ask for access to `field-intelligence-platform`.
3. Accept the invitation: it comes by email, or open https://github.com/field-intelligence-platform and click
   **Join**.
4. Check: when you open
   https://github.com/field-intelligence-platform/Precision-Weed-Detection-and-Targeted-Spraying while logged in,
   you should see the code. A "404 – page not found" means the invitation is not accepted yet.

## 3. Install the tools

### Windows

Open **PowerShell** (Start menu → type "PowerShell" → open it) and run these one at a time. `winget` is built
into Windows 10/11:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
```

Or use the installers from the websites instead:

- Git: https://git-scm.com/download/win. Keep all default options. It includes **Git Credential Manager**, which
  handles your GitHub login.
- Python: https://www.python.org/downloads/. On the first screen of the installer, **tick "Add python.exe to
  PATH"**.

Then **close PowerShell and open a new one**, so it finds the new programs, and check:

```powershell
git --version        # e.g. git version 2.51.0.windows.1
python --version     # e.g. Python 3.12.10
```

If `python --version` opens the Microsoft Store or says "not found": the PATH option was not ticked. Run the Python
installer again → **Modify** → tick **"Add Python to environment variables"**. Or use `py -3.12` instead of `python`
in every command below.

### macOS

```bash
xcode-select --install                 # installs git (a window asks for confirmation)
brew install python@3.12               # needs Homebrew: https://brew.sh
git --version && python3.12 --version
```

On macOS, type `python3.12` wherever this guide says `python` before the environment exists (step 5).

### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip
git --version && python3 --version     # must be 3.10–3.13
```

### Optional: QGIS and VS Code

- QGIS (free GIS program, to look at the maps): https://qgis.org/download/ (the "Long Term Release").
- VS Code: https://code.visualstudio.com/, then install the **Python** extension from the Extensions panel.

## 4. Download the code

> **Planning to contribute changes?** Create your own **fork** of the repo first and clone *that* instead (see
> [CONTRIBUTING.md](CONTRIBUTING.md#making-a-pull-request); team members:
> [docs/MAINTAINERS.md](docs/MAINTAINERS.md#as-a-contributor-through-your-fork)). Everything else in this guide is the same.

Choose a folder for your projects, for example `C:\Users\<you>\Projects` on Windows or `~/Projects` on
macOS/Linux:

```bash
cd C:\Users\<you>\Projects             # macOS/Linux: cd ~/Projects   (create the folder first if needed)
git clone https://github.com/field-intelligence-platform/Precision-Weed-Detection-and-Targeted-Spraying.git
cd Precision-Weed-Detection-and-Targeted-Spraying
```

**The first time you clone**, a window asks you to log in to GitHub. Choose **"Sign in with your browser"** and
confirm. Git Credential Manager remembers the login, so you only do this once. (On macOS/Linux without a credential
manager, use an SSH key instead:
https://docs.github.com/en/authentication/connecting-to-github-with-ssh.)

Then switch to the branch we work on, and turn on the safety check that stops accidental pushes to `main`:

```bash
git switch develop
git config core.hooksPath .githooks
```

Also tell git your name and email, if you have never done so on this computer. Use the email of your GitHub
account, so your commits are linked to you:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## 5. Create a Python environment

A virtual environment ("venv") is a private Python installation just for this project, so its packages never
clash with anything else on your computer. You create it once, inside the project folder:

```bash
python -m venv .venv                   # macOS: python3.12 -m venv .venv · Linux: python3 -m venv .venv
```

Now **activate** it. This has to be done **in every new terminal window** before working on the project:

| Terminal | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Command Prompt (cmd) | `.venv\Scripts\activate.bat` |
| Git Bash (Windows) | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

When it is active, the prompt starts with `(.venv)`. From now on `python` and `pip` mean the project's own copies.

> **PowerShell says "running scripts is disabled on this system"?** Run this once, then try again:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (answer **Y**). It allows scripts you created yourself to run.

## 6. Install weedscout

With the venv active (you see `(.venv)`):

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

- `-e` ("editable") means Python uses the code in this folder directly: when you change a file, the change is live
  without reinstalling.
- `[dev]` also installs the test tools (pytest).
- This downloads numpy, scipy, rasterio, geopandas, shapely, pyproj, pystac-client and their dependencies, about
  300–500 MB. It takes a few minutes. Ready-made packages exist for Windows, macOS and Linux, so nothing needs to be
  compiled.

The last line should say `Successfully installed … weedscout-1.6.0 …` (or a newer version).

## 7. Check that it works

```bash
weedscout --help                       # shows all command-line options
pytest -q                              # runs the offline tests
```

The tests take under a minute and need no internet. The last line should look like:

```
54 passed, 1 warning in 33.43s
```

(The number grows as tests are added. What matters: **no "failed" and no "error"**.)

## 8. Your first scouting map

This analyses three real fields near Göttingen for the 2024 season, the same run as the committed example in
`outputs/example/`:

```bash
weedscout --boundary data/fields/goettingen_example_fields.geojson --year 2024 --out outputs/my_run
```

- It needs the internet: the satellite images (Sentinel-2) come from the free Microsoft Planetary Computer. No
  account or API key is needed.
- It takes about **1–2 minutes**. Each run downloads the images it needs; only the multi-year view and the validation
  experiments keep a cache (`outputs/cache/`).
- It prints what it is doing for each field and ends with a short summary.

**With your own fields:** use any boundary file that farm software or Google Earth exports: GeoJSON, Shapefile
(as a `.zip` or the `.shp` with its `.dbf`, `.shx` and `.prj` next to it), KML/KMZ, GPX or GeoPackage:

```bash
weedscout --boundary path/to/my_fields.kml --year 2025 --out outputs/my_fields_2025
```

`weedscout --help` lists all options: season start/end (`--start`, `--end`), cloud limit (`--max-tile-cloud`),
smallest zone (`--min-zone-ha`), edge buffer (`--edge-buffer-m`) and which column holds the field name
(`--id-column`). The [README](README.md) explains each one, plus the separate **multi-year view** and
**field-visit kit**.

## 9. Look at the results

Each field gets its own folder: `outputs/my_run/<field-id>/`. The most useful files:

| File | What it is | Open with |
|---|---|---|
| `summary.md` | plain-language summary of the field: zones, area, dates used | any text editor, VS Code, GitHub |
| `quicklook.png` | picture of the map | any image viewer |
| `scouting_zones.geojson` | the zones to scout first, with their statistics | QGIS, farm software, https://geojson.io |
| `scouting_zones_shapefile.zip` | the same zones as a Shapefile | farm software, QGIS |
| `scouting_tiers.tif` | the tier map (raster) | QGIS |
| `season_median_ndvi.tif` | crop vigour over the season | QGIS |
| `report.json`, `zone_series.json` | all numbers, for programs (`zone_series.json`: the per-date evidence behind each zone) | VS Code |

**In QGIS:** drag `scouting_tiers.tif` and `scouting_zones.geojson` into the map window. For a background map:
**Browser panel → XYZ Tiles → OpenStreetMap** (double-click).

Read the README section **[Before you use the map](README.md#before-you-use-the-map)** before drawing conclusions. The map shows
where the crop was persistently weaker. It does not say why, and it does not detect weeds.

## 10. Every day after that

Each time you open a new terminal to work on weedscout:

```bash
cd C:\Users\<you>\Projects\Precision-Weed-Detection-and-Targeted-Spraying
.venv\Scripts\Activate.ps1             # or the command for your terminal (step 5)
```

**Getting the newest code** from the team:

```bash
git switch develop
git pull
pip install -e ".[dev]"                # only needed when pyproject.toml changed; harmless otherwise
pytest -q                              # check everything still works
```

**VS Code:** open the project folder (**File → Open Folder**), then **Ctrl+Shift+P → "Python: Select Interpreter"**
→ choose the one in `.venv`. New terminals inside VS Code then activate the venv automatically.

How to propose a change (fork, pull request, what we check) is in [CONTRIBUTING.md](CONTRIBUTING.md).

## 11. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `git clone` says **"Repository not found"** or asks for a password again and again | Your account has no access yet (step 2), or you logged in with a different GitHub account. Windows: **Control Panel → Credential Manager → Windows Credentials**, remove the `git:https://github.com` entry, clone again and log in with the right account. |
| `python` opens the **Microsoft Store** | Python is not on the PATH (step 3), or use `py -3.12 -m venv .venv`. Also: **Settings → Apps → Advanced app settings → App execution aliases** → turn off the two "python" entries. |
| **"running scripts is disabled"** when activating | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (step 5), or use Command Prompt / Git Bash. |
| `weedscout: command not found` / `not recognized` | The venv is not active: the prompt has no `(.venv)`. Activate it (step 5). |
| `pip install` tries to **compile rasterio or GDAL** and fails | Your Python version has no ready-made package: use Python 3.12 (delete `.venv`, create it again with 3.12). |
| `pip install` fails with **SSL / proxy errors** | You are behind a university or company network. Try another network, or ask IT for the proxy settings (`pip install --proxy http://host:port …`). |
| A run says **"no clear dates"** or few dates | Too cloudy in that season or period. Try another year, or a whole season (`--year`) instead of a short period. |
| A run fails with **connection / timeout errors** | The Planetary Computer was briefly unreachable. Run the same command again. |
| **"location information (.prj) is missing"** | A Shapefile was used without its `.prj` file. Export it again with the projection, or zip all its parts together. |
| Tests fail right after `git pull` | Run `pip install -e ".[dev]"` again (a dependency may have changed). If they still fail on `develop`, tell the team in an issue: that should never happen. |
| The push is **"refused: open a pull request"** | That's the safety check: you tried to push to `main`. Push a branch of your fork instead and open a pull request ([CONTRIBUTING.md](CONTRIBUTING.md)). |

Still stuck? Open a Discussion in the repo with the exact command, the full error message and your operating system.

## 12. Remove everything

Everything lives inside the project folder: delete the folder `Precision-Weed-Detection-and-Targeted-Spraying` and
it is gone, including the venv and any image cache. Git, Python and QGIS stay installed for other projects; remove
them in **Settings → Apps** if you don't need them.
