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
  refracts an ambient glow of your own video; a translucent fallback on macOS
  older than 26.
- Live preview stage with one big Start/Stop button and a status line for
  every state.
- Face library sidebar: drag and drop photos, big round thumbnails, click or
  press `1`–`9` to switch instantly (embeddings are cached), `0` for your real
  face, 🎲 for a random generated face.
- Quality presets Fast / Balanced / Best, *Keep my mouth* (mouth mask), blend
  and sharpness sliders.
- Output straight to OBS Virtual Camera at a fixed 1280×720, so Zoom never
  sees the stream restart.
- Keeps working with the window minimised and keeps the Mac awake while live.
- Single instance: launching Mirage again brings the existing window forward.
- `Mirage.app` with an icon (`make app`, `make install-app`) and a one-step
  installer (`make install`).
- English and Russian UI.
- Keyboard shortcuts: `Space`, `1`–`9`, `0`, `⌘O`, `⌘R`, `⌘M`, `⌘Q`.
- Documentation: README in English and Russian, troubleshooting, responsible
  use, design notes, architecture, and a license notice.

### Changed

- The face swap model runs on the Apple Neural Engine. On a MacBook Air M1 it
  takes about 63 ms per frame instead of about 85 ms with the default CoreML
  setting, roughly a third more fps (typically 10–15 fps live on M1).
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

[Unreleased]: https://github.com/RebSem/mirage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RebSem/mirage/releases/tag/v0.1.0
