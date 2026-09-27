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
  refracts an ambient glow of your own video. On macOS older than 26, or with
  *Reduce transparency* on, the window is plain and dark instead.
- Live preview stage with one big Start/Stop button, and a status in the top
  bar for every state (*Loading models…*, *Starting camera…*, *Live* with the
  fps, *Stopping…*, *Models didn't load*).
- Face library sidebar: drag photos onto the window or press `⌘O` (JPEG, PNG,
  WebP, BMP, TIFF and iPhone HEIC), big round thumbnails, click or press
  `1`–`9` to switch instantly (embeddings are cached), `0` for your real face,
  🎲 for a random generated face. Right-click a face to rename it, show it in
  Finder or remove it; removing asks first.
- Quality presets Fast / Balanced / Best, *Keep my mouth* (mouth mask), blend
  and sharpness sliders; under **More**, *Swap everyone in view*, *Fix blue
  tint*, *Smooth edges* and *Show FPS*.
- **Best** adds face enhancement with GPEN-BFR-256 (about 75 MB), downloaded
  automatically the first time you choose Best, or ahead of time with
  `scripts/install.sh --with-enhancer`. If the enhancer can't be loaded, the
  Quality control switches back to Balanced and a toast says so.
- Output straight to OBS Virtual Camera at a fixed 1280×720, so Zoom never
  sees the stream restart when the webcam switches between 4:3 and 16:9.
  Upstream had no virtual camera output; its README suggested capturing the
  preview window in OBS. The classic UI sends to OBS Virtual Camera too.
- Keeps working with the window minimised and keeps the Mac awake while live.
- Single instance: launching Mirage again brings the existing window forward.
- `Mirage.app` with an icon (`make app`, `make install-app`) and a one-step
  installer (`make install`).
- English and Russian UI; in Russian, Qt's own buttons and dialogs are
  translated too.
- Keyboard shortcuts: `Space`, `1`–`9`, `0`, `⌘O`, `⌘R`, `⌘⇧M` (mirror the
  preview; `⌘M` is left to the standard macOS Minimize), `⌘Q`.
- Accessibility: VoiceOver reads the names of faces, icon buttons and settings;
  with *Reduce motion* on, buttons and toggles don't animate and toasts only
  fade.
- The top bar says *Nothing is reaching OBS Virtual Camera* when you have been
  live for a few seconds but Mirage still can't send frames to OBS Virtual
  Camera, and its help button opens the matching troubleshooting section.
- A damaged face-library index is rebuilt from the saved face files (names
  reset to "Face"); the damaged copy is kept as
  `faces/index.corrupt-<time>.json`. A face whose saved data is damaged
  doesn't stop Mirage from starting: you get your real face and a toast that
  says what to do.
- `python -m mirage --demo photo.jpg` adds a fake *Demo* camera for
  screenshots and testing without a webcam.
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
- The swapped face shimmers less: its position is smoothed from one detection
  to the next, and a big jump (a quick head turn) resets the smoothing, so
  the face never lags behind.
- Apple Silicon is required: the installer stops on Intel Macs, and warns
  when less than about 4 GB of disk space is free.
- PySide6 6.9 or newer is required (was 6.7). New macOS-only dependencies:
  pyvirtualcam and PyObjC (Cocoa, Quartz, AVFoundation).
- Clean start and quit: the camera and all worker threads are always released.
- The upstream README moved to `docs/upstream/README.md`; the classic UI still
  works via `make classic` or `python run.py`.

### Fixed

Bugs in Deep-Live-Cam's live mode. Unless marked otherwise, each fix applies
to both Mirage and the classic UI.

- One bad frame stopped live processing for good and froze the video. Now
  that frame shows the plain camera picture and the video keeps going.
- Live mode ended the moment the camera missed a single frame, for example
  when another app touched the camera. Now capture rides out gaps; only
  5 seconds without video end the session, with a message.
- A camera that opened but sent no frames seemed to start, then showed
  nothing. Now starting fails after about 5 seconds with a message.
- The swap went to the leftmost face in view, such as a poster behind you.
  Now it follows the largest face.
- Tight close-up portraits were not recognised as faces, so they couldn't be
  used. Now they are tried again with a dark border around them.
- With an iPhone Continuity Camera nearby, the wrong camera could open: macOS
  cameras were listed only as "Camera 0" and "Camera 1", and those numbers
  shift when a device comes or goes. Now cameras are listed by name and
  remembered by their unique ID, the built-in camera comes first, and OBS
  Virtual Camera is never offered as an input.
- Turning on a face enhancer froze the live video while its model loaded,
  and a load error stopped processing. Now enhancers load in the background
  and kick in once they are ready.
- When the face swap model failed to load, live mode tried to load it again
  on every frame, stalling the video. Now the failure is remembered until you
  press Live (Start in Mirage) again.
- An interrupted first run could leave a half-written CoreML copy of the swap
  model, which then failed to load on every start. The copy is now written
  in one step, and if preparing it fails, the original model is used.
- The random face button gave no face: thispersondoesnotexist.com now serves
  a web page at its main address, and that page was saved as the photo. Now
  the image comes from the site's image address, is checked before use, and
  the download no longer blocks the window.
- A stalled download from the GPEN fallback mirror could hang forever. It now
  gives up after 60 seconds.
- *Classic UI:* pressing Live again while the models were loading froze the
  app for good (a deadlock). Now the models load in the background and the
  second press is ignored.
- *Classic UI:* pressing Live again restarted a session that was already
  running, dropping the camera for a moment. Now it brings the running
  preview to the front; changes apply live.
- *Classic UI:* choosing a new source photo with no face during a live
  session silently turned the swap off, and a file that isn't an image froze
  the video. Now the previous face stays and the status line says no face was
  found.
- *Classic UI:* quitting while live (Destroy, `Ctrl+C` or `⌘Q`) crashed with
  SIGABRT ("QThread: Destroyed while thread is still running"). Now the live
  threads stop and the camera is released before the app quits.
- *Mirage only:* on a fresh install the first Start failed, because OpenCV
  triggered the macOS camera prompt and gave up without waiting. Mirage now
  asks for camera access itself and waits for your answer.

### Security

- Upstream Deep-Live-Cam turned TLS certificate checks off for model
  downloads on macOS, so a model file could have been swapped on the way
  without anyone noticing. Downloads now verify certificates, using
  certifi's CA bundle.

[Unreleased]: https://github.com/RebSem/mirage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RebSem/mirage/releases/tag/v0.1.0
