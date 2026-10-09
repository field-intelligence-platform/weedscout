# Contributing to weedscout

Thanks for helping. weedscout turns free Sentinel-2 imagery into within-field **scouting maps**: zones where the crop
was persistently weaker than the rest of its field. It is the first analysis module of the
[Field Intelligence Platform](https://github.com/field-intelligence-platform/field-intelligence-platform), which
installs a tagged release of this repo.

This guide covers how we work together: where we talk, the two branches and who merges into them, how reviews work, what a change must include,
and how a release is made. Read it once fully. Afterwards, the [checklist](#checklist-before-you-open-a-pull-request)
at the end is enough.

---

## 1. How we plan and where we talk

Everything about the project stays inside the GitHub organisation
[field-intelligence-platform](https://github.com/field-intelligence-platform), so decisions are written down next
to the code and anyone can find them later. Work flows in three steps:

```
Discussions  ──►  Issues  ──►  Boards
refine the idea    concrete tasks, one     priority, status and
until it's clear   person each, in a       deadlines across the
                   version (milestone)     version
```

### Step 1 – Discussions: refine the idea

| Category | Use for |
|---|---|
| **Version planning** | one thread per version, e.g. *"Version planning: weedscout 1.6 – public release"*: goal, proposed scope, open questions |
| **Ideas** | anything new, not yet tied to a version |
| **Decisions** | one thread per settled design choice, so the reasoning can be found later |
| **Q&A** | questions, installation problems |
| **Announcements** | team-wide news; start with *"How we work"* |

(Until the *Version planning* and *Decisions* categories exist, those threads live in **General**.)

- Question, disagree and refine in the thread until the idea is clear.
- A thread is settled with a reply that starts with **"Decided:"** and summarises the outcome. A later change gets a
  new "Decided:" reply, so the history stays readable.
- Only decided work becomes issues: use **"Create issue from discussion"**, or link the issues in the thread.

### Step 2 – Issues: the concrete tasks

Each issue lives in the repo it belongs to (this repo for weedscout itself, the portal repo for how the portal shows it) and is opened with a template (**Bug report**,
**Feature / improvement** or **Task**). Every issue has:

- a **milestone** = the version it ships in, e.g. *weedscout 1.6 – public release*, with that version's deadline;
- labels:

  | Kind | Labels |
  |---|---|
  | Type | `bug`, `enhancement`, `documentation`, `chore` |
  | Priority | `P0` blocking · `P1` high, needed for the version · `P2` medium · `P3` low, someday |
  | Area | `method`, `validation`, `cli`, `output`, `security`, `ci` |
  | Flags | `needs discussion` (decide in Discussions before starting) · `blocked` · `good first issue` |

- **one assignee**: the person doing it. If two people are needed, split it into two issues. Assign yourself
  *before* you start, so nobody builds the same thing twice.
- a **"Done when"** checklist: how we know it's finished, including tests.

### Step 3 – Boards: priority and deadlines

| Board | Shows |
|---|---|
| [Roadmap – all repos](https://github.com/orgs/field-intelligence-platform/projects/1) | every repo on one timeline |
| [weedscout board](https://github.com/orgs/field-intelligence-platform/projects/3) | this repo's issues and pull requests |
| [Portal board](https://github.com/orgs/field-intelligence-platform/projects/2) | the farm portal |

Every item has a **Status**, a **Priority**, a **Start date** and a **Target date**:

| Status | Meaning | Who moves it |
|---|---|---|
| Backlog | not planned for a version yet | whoever plans |
| Planned | in a version, not started | whoever plans |
| In progress | someone is working on it | you, when you start |
| In review | its pull request is open | you, when you open the pull request |
| Done | merged or closed | automatic (board workflow); move it by hand if it doesn't |

We plan in **two-week blocks** and keep target dates realistic: we are both part-time. If a date slips, change it
on the board and say why in the issue, rather than leaving it red.

### Talking to each other

| What | Where |
|---|---|
| Feedback on code | comments on the **pull request** |
| Questions about one task | comments on its **issue** |
| Internal notes (meeting notes, farmer contacts, field-visit plans) | the organisation's private team repo, never in a code repo |

- **Decisions go in writing.** If something was agreed in a call or chat, add a short summary to the issue or
  thread.
- **Mention people** with `@name` when you need their answer. Reply within a few days, even if only "I'll look at
  this on the weekend".
- **No personal data in issues, screenshots or code**: no farmer names, addresses, phone numbers or private field
  locations.

## 2. Branches and roles

Our repos have exactly **two branches**, and no others:

```
main      the final application. Only verified releases from develop, merged by the team leader.
develop   current work. Only reviewed changes that work, merged by the team leader.
```

| Role | Who | How changes reach `develop` |
|---|---|---|
| **Team leader** | organisation owner (currently @gowthamuppalapati) | commits directly to `develop`, after running the checks in [section 5](#5-tests); reviews and merges everyone else's pull requests; makes the releases into `main` |
| **Contributor** | every other team member | works in their own **fork** (a private copy of the repo under their account) and sends each change as a **pull request into `develop`**. Nothing enters `develop` before the team leader has reviewed it against its issue and confirmed it works |

Rules:

- **No extra branches in our repos.** Contributors' work lives in their fork until it is reviewed. (Inside your own
  fork, branches are up to you; one branch per issue is handy, see [section 4](#4-making-a-change-step-by-step).)
- **Never commit directly to `main`.** `main` only changes through the release pull request `develop` → `main`
  ([section 8](#8-releases-and-versions)).
- **`develop` must always work.** Everything in it has been reviewed and tested, so a release can be made from it at
  any time.

### Protecting `main`

GitHub can only enforce branch protection on private repos with a paid plan. Until the repo is public or the plan
changes, `main` is protected by two things:

1. **The rules above.** Only the team leader merges into `main`.
2. **A local hook** that refuses any push to `main` from your computer. Turn it on once after cloning:

   ```bash
   git config core.hooksPath .githooks
   ```

   It only blocks pushes to `main`; everything else works as normal. Merging a pull request on GitHub is not
   affected.

## 3. Getting started

**Setting up a computer for the first time? Follow [INSTALL.md](INSTALL.md)**: every step from an empty machine to
the first scouting map, with troubleshooting. **Contributors clone their fork** instead of the organisation's repo
(see [section 4](#as-a-contributor-through-your-fork)). The short version, for when Git and Python are already installed:

```bash
git clone https://github.com/field-intelligence-platform/Precision-Weed-Detection-and-Targeted-Spraying.git
cd Precision-Weed-Detection-and-Targeted-Spraying
git switch develop
git config core.hooksPath .githooks

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest -q                          # offline tests, under a minute, no network needed
weedscout --boundary data/fields/goettingen_example_fields.geojson --year 2024 --out outputs/my_run
```

- Python 3.10 or newer.
- The repo is private: cloning needs your GitHub login (Git Credential Manager on Windows, or an SSH key).
- No API key is needed for imagery: it comes from the free Microsoft Planetary Computer STAC API. The first run
  downloads data; later runs reuse the cache in `outputs/cache/`.
- The [README](README.md) explains the method, the outputs and the limitations. Read
  "Limitations – read before using the map" before changing anything in the method.

## 4. Making a change, step by step

### As a contributor (through your fork)

**Once: create your fork and connect it**

1. Open the repo on GitHub and click **Fork** (top right) → owner: **your account** → **Create fork**. Your fork is
   private like the original, and only you and the organisation can see it.
2. Clone **your fork** (not the organisation's repo) and connect it to the original, which git calls `upstream`:
   ```bash
   git clone https://github.com/<your-username>/Precision-Weed-Detection-and-Targeted-Spraying.git
   cd Precision-Weed-Detection-and-Targeted-Spraying
   git remote add upstream https://github.com/field-intelligence-platform/Precision-Weed-Detection-and-Targeted-Spraying.git
   git config core.hooksPath .githooks
   ```
   Then follow [INSTALL.md](INSTALL.md) from step 5 (Python environment) for the rest of the setup.

**For each issue**

1. **Pick an issue** from the current version's milestone, highest priority first. Assign yourself, then set it to
   **In progress** on the board. For a bigger change, write two or three sentences in the issue on how you plan to
   do it, and wait for a quick "sounds good" from the team leader before writing code.
2. **Start from the newest `develop`** of the organisation's repo, on a branch in your fork named after the issue:
   ```bash
   git fetch upstream
   git switch -c 42-kml-names upstream/develop
   ```
3. **Write the code and the tests together** (see [section 5](#5-tests)). For a bug: first write a test that fails
   because of the bug, then fix it.
4. **Run the checks locally** (section 5). The review will run them again, but finding problems yourself is faster.
5. **Commit** in small, meaningful steps (see [commit messages](#commit-messages)).
6. **Push to your fork and open a pull request into the organisation's `develop`:**
   ```bash
   git push -u origin 42-kml-names
   ```
   On GitHub, click **Compare & pull request**. Check that the base is **`field-intelligence-platform/…` →
   `develop`**. Fill in the template: write `Fixes #42`, explain how you tested it, and for method changes add the validation numbers
   ([section 5](#5-tests)). Set the issue to **In review** on the board.
7. **Review:** the team leader checks the change against the issue (see [section 10](#10-reviewing-a-pull-request)).
   Answer every comment, either with a fix or a reason why not. To update the pull request, push more commits to the
   same branch of your fork, and don't force-push once the review has started.
8. **The team leader merges** it into `develop` once it works. Then update your copy, delete the branch, and pick
   the next issue:
   ```bash
   git switch develop && git pull upstream develop
   git branch -d 42-kml-names && git push origin --delete 42-kml-names
   ```

### As the team leader

Your own changes go **directly to `develop`**, after the same checks a pull request would get:

1. Assign yourself and set the issue to **In progress**.
2. `git switch develop && git pull`, then change, test, and run all checks from section 5.
3. Commit with `Fixes #…` in the message and `git push`. The issue closes and moves to **Done** by itself.

If a change of yours is large or risky, open a pull request from a fork anyway, so someone can look at it first.

### Commit messages

Write them in English, so the history reads the same for everyone. The style of this repo:

```
Field names win over technical ids when reading boundary files

KML files from farm software often have both a Name and an id column. The id is a
database number that means nothing to the farmer, so the name is used first.

Fixes #42
```

- The **subject line** says what the change does, in the imperative and sentence case, ideally under 72 characters,
  with no full stop at the end.
- The **body** (optional for small changes) says *why*, not how. The diff already shows how.
- **Link the issue** with `Fixes #42` or `Refs #42`. "Fixes" closes the issue automatically when the change reaches
  the default branch.

### Pull request size

Small pull requests get reviewed quickly and well. One pull request = one purpose. If you notice something else on
the way, open an issue for it instead of fixing it in the same pull request. A rough guide: if a pull request is over
~400 changed lines (not counting test data), consider splitting it.

## 5. Tests

- `pytest -q` runs the offline test suite on **synthetic fields**. It never touches the network, so it is fast and
  works anywhere. Keep it that way: tests that need Sentinel-2 data belong in `experiments/`, not `tests/`.
- **Every bug fix comes with a test** that failed before the fix.
- **Every new behaviour comes with tests**, including the unhappy paths: invalid boundary files, fields without
  clear dates, tiny fields, fields crossing UTM zones.
- Use the fixtures in `tests/conftest.py` (`square_field`, `make_observations`) instead of building fields by hand.
- CI runs on every push to `develop`/`main` and on every pull request: a quick Linux check (Python 3.10 and 3.13)
  always, and the full matrix (Linux, Windows, macOS × Python 3.10–3.13) for pull requests into `main`. A pull
  request is merged only when CI is green.

### Changes to the method need validation, not just tests

The unit tests prove the code does what it says. They don't prove the map is right. If you change anything that moves
the results (thresholds, cloud masking, crop units, anomaly scoring, zone cleaning):

1. Re-run the validation in [docs/VALIDATION.md](docs/VALIDATION.md): calibration fields and the 28 out-of-sample
   fields, both seasons.
2. Put the before/after numbers in the pull request (detection rate, chance false alarms, share flagged,
   repeatability).
3. Update `docs/VALIDATION.md` and the README if the numbers change.
4. Re-generate the committed examples in `outputs/example/` if the output changes.

A method change whose validation got worse is not merged without a written reason that both of us agree with.

## 6. Code style

- **Match the code around you**: naming, comment density, how errors are reported. A reader should not be able to
  tell who wrote which file.
- Python 3.10+ syntax, type hints on public functions, docstrings that say what a function is *for*.
- Keep `pipeline.analyse()` **pure** (no file or network I/O); I/O belongs in `sentinel.py`, `boundary.py` and
  `export.py`.
- Raise errors with **messages a farmer could act on** ("the file has no location information (.prj)"), not just
  internal ones.
- **New dependencies need a reason** in the pull request: they make installation slower and can break on some
  systems. Prefer what is already used (numpy, scipy, rasterio, geopandas, shapely, pyproj, pystac-client).
  Add them to `pyproject.toml`, never only to your own environment.
- No commented-out code, debug prints or personal file paths in commits.

## 7. What every feature must respect

These are the project's design rules. A pull request that breaks one of them needs a very good reason.

- **Farmer-openable output.** Results are maps and files farm software opens (GeoTIFF/COG, GeoJSON, Shapefile, KML,
  GPX), not just a plot.
- **No-code input.** Accept the boundary files farmers already have (Shapefile, GeoJSON, KML, GPX).
- **Honest confidence.** Tiers and uncertainty, never an overclaimed single answer. weedscout shows *where to scout
  first*. It does not detect weeds, and no text, label or output may say it does.
- **Free, global data only.** Sentinel-1/2 via the Planetary Computer, or other open data with a licence that allows
  our use. No paid imagery.

## 8. Releases and versions

weedscout uses [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

| Change | Version |
|---|---|
| a bug fix, no change to outputs or options | PATCH: 1.5.1 → 1.5.2 |
| a new option, output file or feature; existing use keeps working | MINOR: 1.5.1 → 1.6.0 |
| an existing option, output or file format changes or disappears | MAJOR: 1.5.1 → 2.0.0 |

**Making a release** (only the team leader). Nothing reaches `main` without being re-run and verified in full:

1. **Freeze `develop`:** no merges while the release is checked. Everything planned for the version's milestone is
   merged, or moved to the next milestone.
2. **Rerun everything on `develop`**, in a fresh virtual environment (`pip install -e ".[dev]"`):
   - [ ] `pytest -q`
   - [ ] the example run (`weedscout --boundary data/fields/goettingen_example_fields.geojson --year 2024 --out
         outputs/release_check`), compared with the committed `outputs/example/`
   - [ ] if the method changed since the last release: the validation in `docs/VALIDATION.md`, numbers updated
   - [ ] the README's commands still work as written
   - [ ] every issue in the milestone is closed, and its "Done when" list really holds
3. **Set the version** in **both** `pyproject.toml` and `src/weedscout/__init__.py`, update the README if needed,
   commit to `develop`.
4. **Open the release pull request `develop` → `main`**, titled `Release 1.6.0`, listing what changed for users and
   the results of step 2. The full CI matrix (Linux, Windows, macOS × Python 3.10–3.13) runs on it and must be green.
5. **Merge** with **"Create a merge commit"** (never squash a release), then tag it and publish release notes:
   ```bash
   git switch main && git pull
   git tag -a v1.6.0 -m "weedscout 1.6.0"
   git push origin v1.6.0
   git switch develop
   ```
   Then on GitHub: **Releases → Draft a new release → choose the tag**, and paste the user-facing notes.
6. The portal picks up the new version only when its pin in `backend/pyproject.toml` (`weedscout @ git+…@v1.6.0`) is
   updated in the portal repo, with the portal's tests passing.

**Urgent fix to a release:** because `develop` only ever contains reviewed, working changes, the fix goes into
`develop` like any other change, and then a PATCH release (`1.6.1`) follows the same steps.

Tags are never moved or deleted once pushed: the portal and anyone else may depend on them.

## 9. Data, licences and what may be committed

- **Licence:** weedscout is licensed under the [Apache License 2.0](LICENSE). By contributing, you agree that your
  contribution is licensed under the same terms (section 5 of the licence). Copyright stays with each author, and
  contributors are credited in the git history and the release notes.
- **Only contribute code you have the right to contribute**: code you wrote, or code under a licence compatible
  with Apache-2.0 (MIT, BSD, Apache), with its notice kept. Never copy code from projects you work on for an employer
  or university unless they explicitly allow it, and never from sources without a clear licence.
- **Data needs a licence that allows our use**, and its attribution goes into [NOTICE](NOTICE) and the README's
  "Data and licences" section. Field boundaries from real farms are committed only with the farmer's written
  consent, and never with names or other personal data.
- **No large files.** Keep committed data and outputs small (a few MB at most). Raw downloads, caches
  (`outputs/cache/`) and large experiment tables stay out of git. They can be regenerated.
- **Never commit secrets**: tokens, passwords, API keys, `.env` files. If it happens, tell the team leader immediately.
  The secret must be revoked; deleting the commit is not enough.

## 10. Reviewing a pull request

The team leader reviews every pull request **against its issue** before it may enter `develop`. Approving means
"I ran it and it works", not "the code looks fine".

1. **Read the issue first**: its steps to reproduce and its "Done when" list.
2. **Get the change onto your computer** (in your clone of the organisation's repo):
   ```bash
   gh pr checkout 42            # the pull request number
   ```
   Run `pip install -e ".[dev]"` again if `pyproject.toml` changed.
3. **Reproduce the issue's steps** (the command and boundary file from the issue). The problem must be gone, and
   every point of "Done when" must hold. For a bug,
   also check the test the contributor added fails without the fix.
4. **Run the checks** from section 5, and look at the CI result on the pull request. CI on a
   pull request from a fork waits for your approval: click **"Approve and run workflows"** once you've seen the
   change.
5. **Read the code** with this list:
   - [ ] Does it do what the issue asked, and nothing unrelated?
   - [ ] Is there a test that would fail without the change?
   - [ ] Are the error messages understandable for a farmer?
   - [ ] If the method changed: validation with before/after numbers, and are they acceptable?
   - [ ] README, `docs/VALIDATION.md`, examples updated where needed?
   - [ ] No secrets, personal data, large files or personal paths?
6. **Decide:**
   - Works and the list holds → **Approve**, then **"Squash and merge"** into `develop`. The issue closes and moves
     to Done.
   - Doesn't work, or something must change → **"Request changes"** with what you saw (steps, screenshots). It does
     not enter `develop` until it works.

Be specific and kind: explain why, suggest how, and say what's good too. Mark optional points as suggestions, so
it's clear what blocks the merge.

Finally, go back to `develop` (`git switch develop`).

## Checklist before you open a pull request

- [ ] Started from the newest `upstream/develop`; the pull request goes from your fork into the organisation's `develop`
- [ ] `pytest -q` passes locally
- [ ] New or changed behaviour has tests; a bug fix has a test that failed before
- [ ] Method changes: validation re-run, numbers in the pull request, docs updated
- [ ] README and docs updated if users see the change
- [ ] Commit messages explain why; the issue is linked (`Fixes #…`); the issue is set to **In review** on the board
- [ ] No secrets, personal data, large files or debug code

Questions about anything here? Open a Discussion. Improvements to this guide are welcome as pull requests too, like any other change.
