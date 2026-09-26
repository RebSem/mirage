# Changelog

All notable changes to Mirage are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

Mirage is built on [Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam);
changes listed here are relative to Deep-Live-Cam `main` as of September 2026
(commit `759e3f9`).

## [Unreleased]

## [0.1.0] - 2026-09-26

The first Mirage release: a macOS-native frontend for Deep-Live-Cam, made for
wearing a different face on video calls, just for fun.

### Added

- One-window app with native macOS Liquid Glass (`NSGlassEffectView`) that
  refracts an ambient glow of your own video; a plain dark window on macOS
  older than 26.
- Live preview stage with one big Start/Stop button and a status line for
  every state.
- Face library sidebar: drag and drop photos, big round thumbnails, click or
  press `1`–`9` to switch instantly (embeddings are cached), `0` for your real
  face, 🎲 for a random generated face.
- Quality presets Fast / Balanced / Best, *Keep my mouth* (mouth mask), blend
  and sharpness sliders; under **More**, *Swap everyone in view*, *Fix blue
  tint*, *Smooth edges* and *Show FPS*.
- **Best** adds face enhancement with GPEN-BFR-256 (about 75 MB), downloaded
  automatically the first time you choose Best, or ahead of time with
  `scripts/install.sh --with-enhancer`. If the enhancer can't be loaded, the
  Quality control switches back to Balanced and a toast says so.
- Output straight to OBS Virtual Camera at a fixed 1280×720, so Zoom never
  sees the stream restart.
- Keeps working with the window minimised and keeps the Mac awake while live.
- Single instance: launching Mirage again brings the existing window forward.
- `Mirage.app` with an icon (`make app`, `make install-app`) and a one-step
  installer (`make install`).
- English and Russian UI.
- Keyboard shortcuts: `Space`, `1`–`9`, `0`, `⌘O`, `⌘R`, `⌘⇧M` (mirror the
  preview; `⌘M` is left to the standard macOS Minimize), `⌘Q`.
- The top bar says *Nothing is reaching OBS Virtual Camera* when you are live
  but OBS's camera extension isn't receiving frames, and its help button opens
  the matching troubleshooting section.
- A damaged face-library index is rebuilt from the saved face files (names
  reset to "Face"); the damaged copy is kept as
  `faces/index.corrupt-<time>.json`.
- `make dev` installs the test and lint tools (pytest, ruff) from
  `requirements-dev.txt`.
- Documentation: README in English and Russian, troubleshooting, responsible
  use, design notes, architecture, and a license notice.

### Changed

- Live video runs at about 14 fps on a MacBook Air M1, up from about 10:
  - the face swap model runs on the Apple Neural Engine: about 63 ms per frame
    instead of about 82 ms with the default CoreML setting (`ALL`);
  - face detection and swapping run in parallel threads, so the GPU and the
    Neural Engine are busy at the same time;
  - the live face detector works at 320 px (about 9 ms instead of 26 ms at
    640); importing photos keeps a separate 640 px detector on the CPU, so
    small faces in photos are still found.
- Apple Silicon is required: the installer stops on Intel Macs, and warns
  when less than about 4 GB of disk space is free.
- Clean start and quit: the camera and all worker threads are always released.
- The upstream README moved to `docs/upstream/README.md`; the classic UI still
  works via `make classic` or `python run.py`.

### Fixed

- The virtual camera restarted when the webcam flipped between 4:3 and 16:9.
- One bad frame killed the processing thread and froze the video.
- Quitting while live (Destroy, `Ctrl+C` or `⌘Q`) crashed with SIGABRT
  ("QThread: Destroyed while thread is still running").
- Pressing Live twice while the models were loading deadlocked the app.
- Pressing Live again restarted a session that was already running.
- The random face button was broken because the site now serves HTML.
- Close-up portraits were not detected as faces.
- Loading the enhancer model froze the video.
- The wrong camera was picked when an iPhone Continuity Camera appeared.
- Capture ended after a single failed camera read.
- The swap jumped to a face on a poster behind you; it now follows the
  largest face.
- The first Start on a fresh install failed: OpenCV triggered the macOS
  camera prompt and gave up right away. Mirage now asks for camera access
  itself and waits for your answer.

### Security

- Model downloads verify TLS certificates (using certifi's CA bundle).
  Upstream Deep-Live-Cam turned certificate checks off on macOS.

[Unreleased]: https://github.com/RebSem/mirage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RebSem/mirage/releases/tag/v0.1.0
