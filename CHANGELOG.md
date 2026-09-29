# Changelog

All notable changes to Mirage are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

Mirage's face-swap engine is
[Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam), included in
`third_party/deep-live-cam/`. Where an entry compares with upstream, it means
Deep-Live-Cam `main` as of September 2026 (commit `759e3f9`).

## [Unreleased]

### Added

- [`third_party/deep-live-cam/README.md`](third_party/deep-live-cam/README.md):
  which upstream commit the engine is based on, every change Mirage made to
  it, and how to update it. `scripts/update_engine.sh` (or
  `make update-engine`) brings in newer Deep-Live-Cam changes with a
  three-way merge and records the new base commit.
- `make install-app` also puts a `Mirage.app` shortcut in the project folder,
  next to the code, so Mirage opens from there too (git ignores it).

### Changed

- The Deep-Live-Cam engine moved from the top of the repository (`modules/`,
  `locales/`, `run.py`, …) into `third_party/deep-live-cam/`, so the
  repository is laid out as Mirage's own, with the engine in a clearly
  labelled folder. The engine is still imported as `modules`, and
  `make classic` works as before. After you pull this change, `make install`
  or `make clean` removes the empty `modules/` folder git leaves behind.
- A clean repository history: the first commit imports the Deep-Live-Cam
  engine exactly as upstream published it at `759e3f9`, and every commit
  after it is Mirage's. Deep-Live-Cam's own history stays in
  [its repository](https://github.com/hacksider/Deep-Live-Cam).
- The READMEs and the app's copyright line (Finder → Get Info) credit the
  engine as "Face-swap engine: Deep-Live-Cam by hacksider and contributors",
  and the READMEs show a screenshot.
- `make test` and CI also run the engine's own tests.
- The window got a polish:
  - **Title bar:** the **Live | Photos & videos** switch sits in the middle
    of the window and no longer moves. In Photos & videos the status pill
    and the OBS Virtual Camera hint show only while a call runs in the
    background, and the **?** button only in Live. Russian *Готово* is now
    *Готов к эфиру*.
  - **Control bars:** the big button is always in the exact centre; on a
    narrow window the *Enhance faces* label folds away into the switch's
    tooltip. **+** is hidden while nothing is open (the big button already
    says **Open…**), and the folder button appears only when the big button
    says something else, such as **Play video** (formerly *Open video*).
  - **Faces in a photo** are lettered A, B, C… so they don't look like the
    gallery's `1`–`9` shortcuts. A face that will be swapped has a solid
    violet-to-blue outline and a chip with the new face's avatar and name; a
    face left as is gets corner marks and, on hover, *Choose a face…*. Chips
    stay inside the photo and never overlap. The photo has rounded corners,
    is labelled *Swapped · hold Space to compare* after a swap, and dims
    while Mirage works, under a small capsule that says what is happening
    (with a progress bar for videos).
  - **The big button never offers something impossible:** *Open another…*
    when no faces were found, a muted *Pick a face on the right* when nobody
    is set to be swapped, and the current step while busy (*Finding
    faces…*, *Swapping faces…*, *Saving…*).
  - **Batches:** a *N photos* header with a subtitle that follows the job,
    count pills (*Saved*, *No face*, *Failed*), a progress bar, bigger
    thumbnails, a status pill on each row and error details under the file
    name. No toast repeats the result while the list is on screen. In
    Russian the buttons read *Заменить в N фото* and *Продолжить · ещё N*.
  - **Empty Photos & videos:** the whole drop zone opens files, with the
    hint *Pick who to become on the right · ⌘⇧O opens files*.
  - **Look:** in Photos & videos only the settings that change a file are
    shown (*Strength*, *Sharpness*, *Keep my mouth*, *Smooth edges*), and
    changing one after a swap turns the big button back into **Swap**.
    *Blend* is now *Strength* (*Сила замены*), *Show FPS* is *Show fps*
    (*Показывать к/с*), the Russian presets are
    *Скорость / Баланс / Качество*, and **More options** (*Дополнительно*)
    is a row with a chevron rather than a switch. *Strength* and
    *Sharpness* have tooltips.
  - **Sidebar:** *Look* sits right under the faces, and opening
    **More options** grows the panel downwards without moving anything.
  - **Live:** the idle stage says *Press Start to go live as Anna* once a
    face is picked, the camera menu has a chevron, the mirror button is a
    quiet ring when on, and toasts float above the control bar instead of
    covering its buttons.

### Removed

- Upstream files Mirage doesn't use: the demo images (`media/`), the Windows
  launchers (`run-cuda.bat`, `run-directml.bat`) and the copy of upstream's
  README (`docs/upstream/README.md`); the READMEs link to
  [the original](https://github.com/hacksider/Deep-Live-Cam/blob/759e3f985811985cf6c00a3e43e9579652c318f5/README.md)
  instead.
- From `requirements.txt`, packages Mirage doesn't use on Apple Silicon:
  upstream's NSFW filter (opennsfw2, keras) and its Windows, Linux and Intel
  Mac packages.

### Fixed

- Opening a folder of photos right after saving a single photo showed a
  folder button that pointed at the old photo.
- Batch thumbnails were squeezed; they are now centre-cropped.
- In Photos & videos the big button offered **Swap** when nothing could be
  swapped (no faces found, or nobody set to be swapped).

## [0.2.0] - 2026-09-28

Photos & videos: swap faces in the photos and videos you already have.

### Added

- **Photos & videos** mode, next to Live: a **Live | Photos & videos** switch
  in the title bar (remembered between launches). The face gallery and the
  *Look* settings are shared, and a live call keeps running in the
  background. The mode keeps its own selected face, so choosing faces for a
  photo never changes (or turns off) the face you wear in a running call. Open files with **Open…**, `⌘⇧O` (*File → Open Photos or
  Video…*) or by dropping files or folders on the stage; photos dropped on
  the sidebar are still added to your faces.
- Mirage decides who gets swapped: you, if a gallery face is marked
  **This is me** and you are in the picture, otherwise the main face (the
  largest; of two about the same size, the one nearer the centre). Everyone
  else is left as is. Faces get numbered outlines (solid: will be swapped,
  dashed: left as is) and a chip with the face each one becomes.
- Click a face in the picture to choose who it becomes, or *Leave as is*.
  The list is sorted by what will look most natural (same gender, similar
  age), with the best ones marked *★ good match*. **Give everyone the
  selected face** swaps every face at once.
- Photos are swapped at full resolution, and **Enhance faces** (on by
  default) restores detail on the swapped faces only with GFPGAN, blended
  through a soft face-shaped mask so hair, background and other people stay
  exactly as they were (about
  0.4–0.5 s per face on a MacBook Air M1; the model, about 370 MB, is
  downloaded the first time). Hold the compare button or `Space` to see the
  original.
- **Save** (`⌘S`) writes `name-mirage.jpg` next to the original (in the
  original's format; HEIC becomes JPEG), never overwriting anything
  (`-mirage-2`, `-mirage-3`, …). EXIF is kept with the orientation reset and
  the old embedded thumbnail removed; the ICC profile and DPI are kept. The
  file's EXIF also says that its faces were swapped with Mirage.
- Batch: drop several photos or a folder and press **Swap in N photos**.
  Each photo gets the automatic choice and is saved next to its original;
  a list shows every file's status (*Saved*, *No face*, *Failed*, …), and
  **Cancel** stops after the current photo; **Continue (N left)** picks up
  where it stopped.
- Videos (MP4, MOV, M4V, MKV, AVI, WebM): **Make video** shows progress and
  the time left and saves `name-mirage.mp4` next to the original. H.264 on
  the Mac's hardware encoder (VideoToolbox, with libx264 as a fallback), the
  original sound (re-encoded to AAC only if needed) and the same frame rate;
  iPhone HDR is tone-mapped to SDR. People are followed by who they are, not
  where they are, so the right face stays on the right person, also across
  shot cuts and brief head turns. **Cancel** (or quitting Mirage) deletes the
  unfinished file. WebM recordings from browsers, which often have no duration
  in their header, open too. About 13–14 fps for a 720p video with one face
  on a MacBook Air M1. *Enhance faces (slower)* adds GPEN-BFR-256 to videos
  (off by default).
- **This is me** / **This isn't me** in a gallery face's right-click menu.
- The face library remembers each face's estimated gender and age, for the
  suggestions. Faces added earlier get theirs the first time a photo or
  video is opened in Photos & videos.
- `make install` installs ffmpeg with Homebrew; videos need it, photos and
  Live work without it.
- Keyboard: `⌘⇧O` opens photos or a video, `⌘S` saves the swapped photo; in
  Photos & videos, hold `Space` to see the original, `1`–`9` and `0` assign
  faces (to the face you clicked, or change the selected face), `Esc`
  deselects the face you clicked.
- The Mac is kept awake during batches and video renders.
- [docs/MEDIA.md](docs/MEDIA.md): how the mode decides, renders and saves.

### Changed

- In Live, dropping a video or a folder on the stage opens it in Photos &
  videos; photos dropped there are still added to your faces.
- `.heif` photos can be dropped onto the sidebar as faces too (`.heic`
  already worked).
- UI text proofread: clearer English and more natural Russian. For example,
  the idle hint now says *In Zoom or Meet, choose “OBS Virtual Camera” as
  your camera*, and when the camera doesn't start Mirage suggests quitting
  other apps that use it or picking another camera.
- Documentation proofread and checked against the code: both READMEs,
  troubleshooting, the design and architecture notes, and NOTICE (which now
  lists the full extent of the changes). The 0.1.0 fixes below now say what
  you saw before and what happens now.

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

[Unreleased]: https://github.com/RebSem/mirage/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/RebSem/mirage/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RebSem/mirage/releases/tag/v0.1.0
