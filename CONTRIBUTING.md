# Contributing to weedscout

Thank you for your interest! weedscout turns free Sentinel-2 imagery and a field-boundary file into a map of where to
scout first. It is maintained by a small part-time team, so clear, focused contributions help most.

## Ways to help

| You can… | How |
|---|---|
| **Check it on a field you know** – the most valuable help right now | Run it on a field whose problem spots you know, and tell us whether the zones match, good or bad. See [Help us check it in the field](README.md#help-us-check-it-in-the-field), and share in [Discussions](https://github.com/field-intelligence-platform/weedscout/discussions) (*Show and tell*) |
| Ask a question or suggest an idea | [Discussions](https://github.com/field-intelligence-platform/weedscout/discussions) (*Q&A*, *Ideas*) |
| Report a bug | [Open an issue](https://github.com/field-intelligence-platform/weedscout/issues/new/choose) with the command, the error and your system. Never attach real farm data – an anonymised or synthetic boundary file is enough |
| Report a security problem | Privately, as described in [SECURITY.md](SECURITY.md) – not in a public issue |
| Improve the documentation or the code | A pull request, as described below |

## Before you write code

**For anything bigger than a small fix, open an issue or a discussion first** and describe what you plan. We may already
be working on it, or know of a reason it won't work – a short exchange saves you time.

Good first contributions: clearer error messages, documentation, support for another boundary-file variant, tests for
an edge case.

## Making a pull request

1. **Fork** this repo (button top right) and clone your fork. Set it up as described in [INSTALL.md](INSTALL.md), then
   install the development tools:
   ```bash
   pip install -e ".[dev]"
   ```
2. **Create a branch** in your fork from the latest `main`:
   ```bash
   git switch -c fix-kml-names
   ```
3. **Write the change and its tests together** (see [What a pull request needs](#what-a-pull-request-needs)).
4. **Run the tests:** `pytest -q` (offline, under a minute).
5. **Push to your fork and open a pull request** against `main` of this repo. Fill in the template: what and why, how
   you tested it, and – for changes to the results – the validation numbers.

**What happens next:** a maintainer reviews your pull request – reads it, runs it, and checks the tests. We may ask for
changes; please answer every comment. When it is accepted, it goes into our development line and **ships with the
next release**. Your commits keep you as the author, the pull request is marked as merged when that release is
published, and you are named in the release notes.

## What a pull request needs

- **One purpose.** If you notice something else on the way, open a separate issue.
- **Tests:** every bug fix with a test that fails without the fix; every new behaviour with tests, including the
  unhappy paths (invalid files, too few clear images, tiny fields). Tests must run offline – use the fixtures in
  `tests/conftest.py`.
- **Validation for changes to the results.** Unit tests show the code does what it says; they don't show the map is
  right. If you change anything that moves the results (thresholds, cloud masking, crop units, scoring, zone cleaning),
  re-run the validation in [docs/VALIDATION.md](docs/VALIDATION.md) and put the before/after numbers in the pull
  request. A change that makes the validation worse needs a very good written reason.
- **Code style:** match the code around you. Python 3.10+, type hints on public functions, docstrings that say what a
  function is *for*, error messages a farmer could act on. New dependencies need a reason.
- **Commit messages** in English: a short subject saying what the change does ("Read field names from KMZ files"),
  and a body saying *why* if it isn't obvious.

## The project's design rules

A change that breaks one of these needs a very good reason:

- **Honest confidence.** weedscout shows *where to scout first*. It does not detect weeds, and no text, label or output
  may say it does. Show uncertainty; never overclaim.
- **Output farmers can open:** maps and files farm software reads (GeoTIFF, GeoJSON, Shapefile, KML, GPX).
- **No-code input:** the boundary files farmers already have.
- **Free, global data only:** Sentinel-2 (and other open data with a licence that allows our use). No paid imagery.

## Licence and what you may contribute

- weedscout is licensed under the [Apache License 2.0](LICENSE). By contributing, you agree that your contribution is
  licensed under the same terms (section 5 of the licence). You keep the copyright of your work.
- Only contribute code you wrote yourself, or code under a compatible licence (MIT, BSD, Apache) with its notice kept.
  Never copy code from an employer's or university's project unless they explicitly allow it.
- Data needs a licence that allows our use; its source goes into [NOTICE](NOTICE). Never commit real farm boundaries
  without the farmer's written consent, and never personal data. No large files, no secrets.

## Be kind

Be respectful and constructive with everyone – in issues, discussions and reviews. Assume good intent, explain the
*why*, and remember that people here help in their free time. Harassment or personal attacks are not tolerated;
maintainers may remove such content and block those responsible.

Thank you for helping make weedscout better.
