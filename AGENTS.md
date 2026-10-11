# AGENTS.md — Mirage

Guide for coding agents (Claude Code, Codex, Cursor, …) working in this repository.
Checked against the code, git history, CI and GitHub on 2026-10-11.
This repository is **public** and **AGPL-3.0** — never commit personal data, local absolute paths, model files, or photos of real people.

## What this is

Mirage is a macOS app for **Apple Silicon** Macs that swaps faces **live on video calls** (camera → swapped face → OBS Virtual Camera → Zoom / Meet / FaceTime) and **in existing photos and videos**.
It is a Python 3.14 desktop app (PySide6 + PyObjC, native Liquid Glass on macOS 26) that runs entirely on the user's Mac; the swap model runs on the Neural Engine through ONNX Runtime + CoreML.
The face-swap engine is a vendored, lightly modified copy of [Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam) (hacksider and contributors, AGPL-3.0); everything you see and click is Mirage's own code.
Personal, "just-for-fun, spare-time" open-source project of [@RebSem](https://github.com/RebSem) (CONTRIBUTING.md); released versions 0.1.0 and 0.2.0 (September 2026); non-commercial use only because of the model licenses.

## Who owns what: Mirage vs upstream Deep-Live-Cam

| Path | Owner | Notes |
|---|---|---|
| `mirage/` | **Mirage** | The whole app: window, Liquid Glass, face library, live engine (`engine.py`), Photos & videos (`media/`, `ui/media_*.py`), i18n, settings. Most work happens here. |
| `scripts/`, `Makefile`, `tests/mirage/`, `docs/`, `assets/` | **Mirage** | Installer, app bundle, icon, benchmark, engine-update script; Mirage's tests and docs. |
| `README.md`, `README.ru.md`, `CHANGELOG.md`, `NOTICE.md`, `CONTRIBUTING.md`, `AGENTS.md` | **Mirage** | Some started as upstream files in the import commit and were rewritten. |
| `requirements*.txt`, `pyproject.toml`, `.github/`, `.gitignore`, `.gitattributes`, `models/instructions.txt` | **Mirage** (derived from upstream's) | `requirements.txt` was cut down to Apple Silicon (no NSFW filter / Windows / Linux / Intel packages). |
| `LICENSE` | **Upstream, unchanged** | AGPL-3.0. Do not edit. |
| `third_party/deep-live-cam/` | **Upstream Deep-Live-Cam** (+ Mirage's small changes) | `modules/` (the engine, imported as top-level package `modules`), `locales/`, `run.py` + `tkinter_fix.py` (classic window, `make classic`), `tests/` (two upstream tests), `benchmark_pipeline.py`, `mypi.ini`, `LICENSE` (copy). |
| `third_party/deep-live-cam/README.md`, `UPSTREAM_COMMIT`, `models` (symlink → `../../models`), `modules/virtualcam_out.py` | **Mirage, inside the vendored folder** | The README's table "What Mirage changed" is the authoritative list of every modified engine file (AGPL §5(a) notice). |

GitHub's language stats ignore `third_party/**` (`linguist-vendored` in `.gitattributes`).

## Current state

- **Default branch:** `main`. Last commit `b32db93` "Fix bugs found in a review of the whole app" (2026-09-29).
- **Version:** `0.2.0` (`mirage/__init__.py: __version__`, tag/GitHub Release `v0.2.0`, CHANGELOG `[0.2.0] - 2026-09-28`). `CHANGELOG.md → [Unreleased]` lists sizeable changes on `main` since then (engine moved to `third_party/`, clean history, CoreML compiled-model cache, window polish, quick quit, fixes) — not released yet.
- **CI is red on `main`** since the 2026-09-29 push that added the CoreML cache tests (`100acd7`; the runs on `ab37e51` and `b32db93` failed): the `mirage-ci` job installs only `numpy opencv-python-headless pillow pytest ruff`, but `tests/mirage/test_coreml_cache.py::test_a_broken_cache_falls_back_to_a_plain_load` does `import onnxruntime` → `ModuleNotFoundError`. Everything else passes (CI: 1 failed, 167 passed, 23 skipped). Fix (owner's call): `pytest.importorskip("onnxruntime")` in that test, or add `onnxruntime` to the CI install step. The `ruff` workflow is green.
- **Open PRs (both Dependabot, opened 2026-09-29; their latest CI runs on 2026-10-01 fail with the same onnxruntime error as `main`, not because of the bumps):**
  - **#7** GitHub Actions group: `actions/checkout` v4 → v7, `actions/setup-python` v5 → v7, `astral-sh/ruff-action` 4.0.0 → 4.1.0.
  - **#8** Python group, 13 updates incl. majors: `opencv-python(-headless)` 4.14.0.94 → 5.0.0.93, `insightface` 0.7.3 → 2.0, `onnxruntime` 1.28.0 → 1.30.0, `onnx` 1.22.0 → 1.23.0, `PySide6>=6.11.2`, `numpy>=2.5.3`, `protobuf>=7.36.2`, `pytest>=9.1.1`, `ruff` 0.15.7 → 0.16.9. Caveats: the ruff bump would desync from `Makefile` (`RUFF_VERSION := 0.15.7`) and both workflows (pinned 0.15.7); `insightface` 0.7.3 → 2.0 and OpenCV 4 → 5 are major-version jumps from the pinned versions and CI does not install either — check with a real `make install` + live/photo/video run before merging.
  - Earlier single-package Dependabot PRs #1–#5 were closed; #6 (Photos & videos mode) was merged.
- **Branches on GitHub:** only `main` and the two Dependabot branches. No `wip/*` branch for this repo.
- **Upstream drift:** `UPSTREAM_COMMIT` = `759e3f9` (Deep-Live-Cam `main`, 2026-09-26). On 2026-10-11 upstream `main` was 10 commits ahead (`a924275`, 2026-10-10), touching `modules/model_downloader.py`, `modules/utilities.py`, `modules/ui.py` (all three carry Mirage changes → expect 3-way conflicts), new `locales/tr.json`, and upstream's `requirements.txt`.
- **Known gaps:** Intel Macs and macOS < 14 unsupported by design; Liquid Glass only on macOS 26 (older gets a plain dark window); CI runs on Python 3.12 with a light dependency set, so tests that need the heavy stack are skipped there (`importorskip`).

## Repository map

```
mirage/                    the app (package map with every module: docs/ARCHITECTURE.md)
  __init__.py              __version__, APP_NAME, BUNDLE_ID, REPO_URL, UPSTREAM_URL; puts third_party/deep-live-cam on sys.path
  __main__.py, app.py      `python -m mirage` → QApplication, single instance, logging, quit cleanup
  engine.py                LiveEngine: capture / detect / process threads → OBS Virtual Camera + preview
  upstream.py              configures the Deep-Live-Cam engine once (CoreML, 320 px live detector, compiled-model cache)
  library.py, faces_ai.py  face library (index.json + jpg/thumb/npy) and photo → embedding
  media/                   Photos & videos pipeline: analyze, plan, render, photo_io, batch, video (ffmpeg)
  ui/                      main window, stage, faces sidebar, look panel, media page/view, toasts, widgets
  glass.py, theme.py       native NSGlassEffectView behind Qt widgets; colours, radii, motion, Qt stylesheet
  i18n.py                  every UI string, English + Russian
  camera.py, tracking.py, power.py, paths.py, settings.py, demo.py
third_party/deep-live-cam/ vendored engine (see table above and its README)
scripts/                   install.sh, build_app.sh, update_engine.sh, benchmark.py, make_icon.py
tests/mirage/              Mirage unit tests (no models, camera, network or display needed)
docs/                      ARCHITECTURE, DESIGN, MEDIA, TROUBLESHOOTING, RESPONSIBLE_USE, images/
models/                    downloaded models (gitignored; only instructions.txt is tracked)
assets/icon/               app icon (.icns + PNGs)
.github/                   workflows mirage-ci.yml (macos-14) + ruff.yml, dependabot.yml (monthly, grouped), issue templates
```

## Commands

Everything goes through the `Makefile` (`make` lists targets). Requires an Apple Silicon Mac, Homebrew and Xcode Command Line Tools.

```bash
make install                         # scripts/install.sh: Homebrew Python 3.14, ./venv, requirements, models, ffmpeg; offers OBS. Re-runnable
make install ARGS="--with-enhancer --yes"   # also GPEN-BFR-256 (~75 MB); answer yes to everything (installs OBS)
make install-app                     # build Mirage.app → ~/Applications + a Mirage.app shortcut in the repo folder
make app                             # build dist/Mirage.app only
make run                             # = venv/bin/python -m mirage
venv/bin/python -m mirage --debug    # also: --version, --demo PHOTO (fake "Demo" camera, no webcam needed)
make classic                         # the classic Deep-Live-Cam window (third_party/deep-live-cam/run.py --execution-provider coreml)
make dev                             # pytest + ruff into the venv (requirements-dev.txt)
make test                            # pytest -q tests/mirage third_party/deep-live-cam/tests
make lint                            # ruff check mirage tests scripts third_party (+ shellcheck scripts/*.sh if installed)
make bench                           # time the swap model per CoreML compute unit
make icon                            # redraw assets/icon
make clean                           # remove dist/, build/, __pycache__ (keeps the installed app)
make update-engine [REF=<commit>]    # pull upstream Deep-Live-Cam changes (see "Syncing with upstream")
```

CI equivalent without the full install (what `mirage-ci` does):

```bash
python3 -m venv /tmp/mirage-ci && /tmp/mirage-ci/bin/pip install numpy opencv-python-headless pillow pytest "ruff==0.15.7"
/tmp/mirage-ci/bin/ruff check mirage tests scripts third_party
/tmp/mirage-ci/bin/python -m pytest -q tests/mirage third_party/deep-live-cam/tests
```

Verified on 2026-10-11 (Python 3.14.7, numpy 2.5.4, opencv-python-headless 5.0.0.93, pillow 12.3.0, pytest 9.1.1, ruff 0.15.7):
`ruff check mirage tests scripts third_party` → all checks passed; pytest (CI command) → **1 failed** (the onnxruntime test above), 188 passed, 2 skipped; after `pip install onnxruntime==1.28.0` `tests/mirage/test_coreml_cache.py` → 5 passed. Also `make help`, `scripts/install.sh --help`, `scripts/build_app.sh --help`; `make run` without a venv prints "run make install first".
**Not run:** `make install` (Homebrew + ~6 GB of packages/models), `make run` / `make classic` with a camera, `make app`, `make bench`, `make update-engine`.

## Configuration

- **No secrets, no API keys.** The network is used only for model downloads (Hugging Face `hacksider/deep-live-cam`, InsightFace `buffalo_l`) and the 🎲 random face (thispersondoesnotexist.com).
- **Env vars:** `MIRAGE_HOME` — redirects app data, logs and cache into one folder (tests use it; never let tests touch the real library). `XDG_DATA_HOME` / `XDG_CACHE_HOME` — only for the non-macOS fallback paths. `LANG` — fallback for UI language detection when `NSLocale` is unavailable. `NO_COLOR` — plain output from `install.sh` / `build_app.sh`.
- **User data (outside the repo):** faces + `settings.json` in `~/Library/Application Support/Mirage`, logs in `~/Library/Logs/Mirage`, compiled CoreML models in `~/Library/Caches/Mirage` (safe to delete). Settings schema: `mirage/settings.py` (documented in docs/ARCHITECTURE.md).
- **Models:** `./models/` (gitignored): `inswapper_128_fp16.onnx`, `GPEN-BFR-256.onnx`, `gfpgan-1024.onnx` + generated `*_coreml*.onnx`; `buffalo_l` in `~/.insightface/models`. See `models/instructions.txt`.
- **Results** of Photos & videos are written next to the originals as `<name>-mirage.<ext>`; originals are never modified.
- `pyproject.toml`: ruff (`target-version = "py310"`, a deliberately small rule set) and pytest paths (`.` and `third_party/deep-live-cam`).

## Deploy & release

- No server and no binary distribution: users `git clone` and run `make install` + `make install-app`. `Mirage.app` is a thin, ad-hoc-signed bundle (bundle id `io.github.rebsem.mirage`) that runs **this checkout's** `venv` — it breaks if the folder moves (re-run `make install-app`).
- Releases: tag `vX.Y.Z` + GitHub Release with notes (v0.1.0 2026-09-26, v0.2.0 2026-09-28), no assets. Versioning is SemVer; `CHANGELOG.md` follows Keep a Changelog (add user-visible changes under *Unreleased*). `build_app.sh` reads the version from `mirage/__init__.py`.
- CI (GitHub Actions) on every PR and push to `main`: `mirage-ci` (macos-14, Python 3.12, ruff + pytest) and `ruff` (ubuntu). Dependabot: monthly, grouped, for pip and GitHub Actions.

## Conventions

- Typed Python, short comments that explain *why*. Ruff 0.15.7 is the pinned linter (`Makefile`, both workflows, `requirements-dev.txt`) — keep the pins in sync.
- **Every UI string goes into `mirage/i18n.py` in English and Russian**; `tests/mirage/test_i18n.py` checks parity. User docs: README in English and Russian (`README.ru.md`) kept in sync; all other docs English.
- Threads are plain `threading.Thread` (not `QThread`); results go back to the UI thread via queued Qt signals carrying a job **token** (stale results are dropped). See docs/ARCHITECTURE.md.
- No modal error dialogs during a live session — use toasts (docs/DESIGN.md).
- Tests in `tests/mirage/` must run **without models, camera, network or display** — use fakes, point `MIRAGE_HOME` at a temp dir; ffmpeg-dependent tests skip when ffmpeg is missing.
- Commits: CONTRIBUTING.md asks for Conventional Commits (`feat(scope):`, `fix:`, `docs:`, `build:`, `perf:`, …). Recent history also uses plain imperative subjects ("Keep compiled CoreML models between launches …") and area prefixes like `ui:`, with a detailed body; commits carry a `Co-Authored-By: Claude …` trailer. Feature work went through a PR (#6 `feature/media-swap`).
- PR checklist (CONTRIBUTING.md): `make test` + `make lint`; if the live path changed, start a session, switch faces, quit with `⌘Q` **while live** (camera light must go off, no crash); if the engine changed, `make classic` still starts and the engine README's change list is updated; CHANGELOG line for user-visible changes; screenshots use generated faces, never real people.

## Rules / what must not break

- **Upstream obligations (AGPL-3.0):** keep `LICENSE` unchanged; keep copyright notices in engine code; keep the attribution to Deep-Live-Cam (hacksider and contributors), roop, InsightFace, GFPGAN, GPEN in README.md / README.ru.md / NOTICE.md, and the "Face-swap engine: Deep-Live-Cam by hacksider and contributors" credit in the app's copyright line (`NSHumanReadableCopyright` in `scripts/build_app.sh`); every change to `third_party/deep-live-cam/` must be added to "What Mirage changed" in `third_party/deep-live-cam/README.md` (the §5(a) notice NOTICE.md points to). Mirage stays AGPL-3.0; full source must stay public.
- **Models are non-commercial** (InsightFace terms) and are **never committed**; no datasets or photos of real people in the repo. Keep the Responsible use guidance (docs/RESPONSIBLE_USE.md) intact.
- **Keep engine diffs small:** prefer adding code in `mirage/`; if you must touch the engine, change as little as possible and explain why in the commit message (easier upstream merges). Consider sending generally useful fixes upstream.
- The engine package must stay importable as `modules` (`mirage/__init__.py` path insert + `pyproject.toml` pythonpath); code outside `mirage/` that needs the engine must `import mirage` first.
- `configure_upstream()` must run before Deep-Live-Cam's face analyser is first created (insightface fixes detector size/providers at that point).
- The `third_party/deep-live-cam/models` symlink → `../../models`, `UPSTREAM_COMMIT` and the tracked `models/instructions.txt` must stay (`tests/mirage/test_engine_layout.py` checks the link, the recorded commit and that `import mirage` makes `modules` importable).
- Virtual camera output stays a fixed 1280×720; the preview may be mirrored, the virtual camera never.
- Quitting (`⌘Q`, window close, SIGINT/SIGTERM) must stop the camera and any job promptly and never leave half-written files.
- Requirements: keep `PySide6>=6.9` (window hints); Apple Silicon only (`install.sh` stops on Intel).
- Keep the privacy promise (README "Your data"): camera, photos and videos are processed on the Mac and never uploaded.
- Ask the owner before: merging Dependabot majors (#8), rewriting history (it was already done once, see below), changing license/attribution text.

## Syncing with upstream Deep-Live-Cam

The repo is **not** a GitHub fork and does not contain upstream's git history; the engine is vendored at the commit in `third_party/deep-live-cam/UPSTREAM_COMMIT`. To update:

```bash
git status                 # must be clean — the script refuses otherwise
make update-engine         # = scripts/update_engine.sh  (latest upstream main)
make update-engine REF=<upstream-commit>
```

What the script does: fetches `https://github.com/hacksider/Deep-Live-Cam.git` by URL (no git remote needed), diffs `UPSTREAM_COMMIT..new` **only for the vendored paths** (`modules`, `locales`, `run.py`, `tkinter_fix.py`, `benchmark_pipeline.py`, `mypi.ini`, the two vendored tests), applies it with `git apply --3way --directory=third_party/deep-live-cam`, writes the new SHA to `UPSTREAM_COMMIT`, and **does not commit**.
Then: resolve conflict markers → compare upstream's requirements (`git diff <old> <new> -- requirements.txt`, the script prints the command) against ours → `make test` → try `make run` **and** `make classic` → update the engine README change list and CHANGELOG → commit.
Upstream's README, media, CI, Windows launchers and other tests are intentionally not vendored.

## History & key decisions

- 2026-09-26 `f01a8a6` — repo's first commit: Deep-Live-Cam tree at `759e3f9`, unchanged (AGPL-3.0).
- 2026-09-26 — engine fixes: stable macOS live mode, TLS-verified model downloads, swap model on the Neural Engine (`CPUAndNeuralEngine`, ~63 ms vs ~82 ms per frame on M1).
- 2026-09-26 `1e47e6a` — Mirage app (Liquid Glass, PySide6/PyObjC); installer, `Mirage.app`, icon, benchmark, CI; README en/ru, NOTICE, design/architecture/troubleshooting/responsible-use docs. Apple Silicon only, GPEN-256 for `--with-enhancer`, PySide6 ≥ 6.9. **v0.1.0**.
- 2026-09-28 `05ec82c` (PR #6) — Photos & videos mode: photos, batches, videos with sound and identity tracking. **v0.2.0**.
- 2026-09-29 `4b80faa` — engine moved from the repo root into `third_party/deep-live-cam/` with `UPSTREAM_COMMIT`, change list and `update_engine.sh`; upstream demo media / Windows launchers / README copy removed.
- 2026-09-29 — **repository history rewritten** to a clean history (CHANGELOG *Unreleased*: "the first commit imports the Deep-Live-Cam engine … every commit after it is Mirage's"); tags `v0.1.0` / `v0.2.0` now point into the new history. The pre-rewrite history is not on GitHub — ask the owner if you need it.
- 2026-09-29 — compiled CoreML model cache (warm-up 15–19 s → 5–7 s), immediate quit, a whole-app review fix batch (`b32db93`).
- 2026-09-29 — Dependabot PRs #7, #8 opened; CI red since the cache commit's onnxruntime test.

## Gotchas

- **Old clones can't simply `git pull`:** a clone made before the 2026-09-29 history rewrite shares no commits with the current `main` (its root is `f01a8a6`), yet the v0.2.0 release notes say `git pull` to upgrade. Such users need a fresh clone (or `git fetch` + `git reset --hard origin/main`, which discards local changes).
- `.gitignore` ignores `*.png`, `*.mp4`, `*.mkv` globally (inherited from upstream) with exceptions only for `assets/**/*.png` and `docs/images/*.png` — a new PNG elsewhere is silently ignored. It also ignores `/models` (but `models/instructions.txt` is tracked on purpose) and the whole `/.claude` folder.
- The first commit contains upstream's demo GIFs (about 67 MB in `media/`, removed later), so a full clone is ~67 MB even though the current tree is small; `gh repo clone RebSem/mirage -- --filter=blob:limit=5m` is faster.
- `import modules` only works after `import mirage` (or with pytest's configured `pythonpath`).
- CI uses Python 3.12 and a light install, the app uses Python 3.14 and the full `requirements.txt` — a test that imports a heavy package (onnxruntime, insightface, PySide6) must `pytest.importorskip` it or CI breaks (this is exactly why CI is red now).
- Compiled CoreML models are cached in `~/Library/Caches/Mirage/coreml`, one folder per model file version (name + size + mtime, because ONNX Runtime keys its cache by path only); a cache that fails to load is deleted and rebuilt. The first launch after install or a model change is slow (~15–19 s on M1), later ones ~5–7 s.
- `make lint` uses `venv/bin/ruff`, else `ruff` on PATH, else `uvx ruff@0.15.7`.
- `Mirage.app` and the repo-folder `Mirage.app` shortcut run this checkout's `venv`; after moving the folder, run `make install-app` again.
- After pulling the 2026-09-29 engine move into an old checkout, `make install` or `make clean` removes the empty `./modules` folder git leaves behind.

## Where to look next

- `docs/ARCHITECTURE.md` — the contract: threads, package map, paths, settings, library, engine signals, quitting, glass.
- `docs/DESIGN.md` — UI rules, tokens, how the Liquid Glass works, adding a glass panel.
- `docs/MEDIA.md` — Photos & videos pipeline in detail.
- `docs/TROUBLESHOOTING.md` — user-facing fixes (camera permission, OBS, fps, install errors).
- `docs/RESPONSIBLE_USE.md`, `NOTICE.md` — use policy, licenses, third-party components.
- `third_party/deep-live-cam/README.md` — engine origin, change list, update procedure.
- `CONTRIBUTING.md`, `CHANGELOG.md`.
