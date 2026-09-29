# Contributing to Mirage

Thanks for wanting to help! Mirage is a just-for-fun, spare-time project, so
the process is light. Small, focused pull requests are the easiest to review
and the quickest to land.

## Getting set up

```bash
git clone https://github.com/RebSem/mirage
cd mirage
make install      # Python 3.14 via Homebrew, venv, models
make dev          # pytest and ruff from requirements-dev.txt
make run          # start Mirage from the checkout
```

You need an Apple Silicon Mac (the installer stops on Intel). Mirage needs
PySide6 6.9 or newer for its window hints; `requirements.txt` already asks
for it, so keep that pin if you touch the requirements.

For anything beyond the basics, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
first. It is the contract for how the app is put together.

## Where things live

| Path | What it is | How to treat it |
|---|---|---|
| `mirage/` | the Mirage app: window, face library, live engine, Photos & videos, Liquid Glass | this is where most work happens |
| `third_party/deep-live-cam/` | the face-swap engine: Deep-Live-Cam with Mirage's fixes (`modules/`, `locales/`, and `run.py` for the classic window) | **keep diffs small** (see below) |
| `scripts/` | installer, app bundle, icon, benchmark, engine update | |
| `tests/mirage/` | unit tests for `mirage/` | |
| `docs/` | documentation | |
| `models/` | downloaded models (not in git) | never commit model files |

### Changing the engine

`third_party/deep-live-cam/` is Deep-Live-Cam's code, imported unchanged from
upstream commit `759e3f9`. The smaller our changes there, the easier it is to
pull in upstream improvements later. So:

- Prefer adding code in `mirage/` over changing the engine.
- If you must change it, change as little as possible, explain why in the
  commit message, and add the change to the list in
  [third_party/deep-live-cam/README.md](third_party/deep-live-cam/README.md#what-mirage-changed).
- The engine's Python package is still called `modules`, because its code
  imports `modules.*` everywhere. `mirage/__init__.py` puts
  `third_party/deep-live-cam` on `sys.path`, and `pyproject.toml` does the
  same for pytest, so `import modules` works in the app and in the tests.
- If a fix is useful for everyone, consider also sending it upstream to
  [Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam).
- Make sure `make classic` still starts.
- To move to a newer Deep-Live-Cam, run `scripts/update_engine.sh` (see
  [Updating from upstream](third_party/deep-live-cam/README.md#updating-from-upstream)).

## Tests and lint

```bash
make test         # unit tests: tests/mirage and the engine's own tests
make lint         # ruff, plus shellcheck on scripts/*.sh if you have it
```

Both use the tools listed in `requirements-dev.txt` (pytest and ruff), which
`make dev` installs; `make test` runs it for you the first time. CI runs
ruff and both sets of unit tests on every pull request.

Tests in `tests/mirage/` must run **without models, a camera, network access
or a display**. Use fakes (for example a fake embedder for the face library)
instead of real models, and point `MIRAGE_HOME` at a temporary folder so tests
never touch your real faces and settings.

A few more rules of thumb:

- Typed Python, short comments that explain *why*, no filler.
- Every UI string goes into `mirage/i18n.py` in **both English and Russian**;
  a test checks that the two stay in sync.
- No modal error dialogs during a live session; use a toast. See
  [docs/DESIGN.md](docs/DESIGN.md).

## Before you open a pull request

- [ ] `make test` and `make lint` pass.
- [ ] If you touched the live path: start a session, switch a few faces, then
      quit with `⌘Q` **while live**. The camera light should go off and
      nothing should crash.
- [ ] If you touched `third_party/deep-live-cam/`: `make classic` still
      starts, and the list of changes in its README is up to date.
- [ ] If users will notice the change: add a line to
      [CHANGELOG.md](CHANGELOG.md) under *Unreleased*.
- [ ] Screenshots or a short clip for visual changes (a generated face, not a
      real person, please).

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(library): drag several photos at once
fix(engine): keep the virtual camera open when the webcam changes aspect
docs: explain the OBS system extension prompt
```

Common types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`,
`chore`. The scope is optional; use the module or area name.

## Credit and license

Mirage's face-swap engine is
[Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam) by hacksider and
contributors. Keep the copyright notices in its code intact, and credit its
authors when you port their work.

By contributing you agree that your contribution is licensed under the
[AGPL-3.0](LICENSE), the same license as the rest of the project. Please do
not add models, datasets or photos of real people to the repository; see
[NOTICE.md](NOTICE.md) for why models are downloaded separately.

## Be kind

Be friendly and patient in issues and reviews. Requests for help with
deceiving, harassing or impersonating people will be closed; see
[docs/RESPONSIBLE_USE.md](docs/RESPONSIBLE_USE.md).
