<p align="right"><b>English</b> · <a href="README.ru.md">Русский</a></p>

<h1 align="center">Mirage</h1>

<p align="center">
  Wear a different face on video calls, live, and in your photos and videos.
  On your Mac, just for fun.
</p>

<p align="center">
  <sub>Face-swap engine: <a href="https://github.com/hacksider/Deep-Live-Cam">Deep-Live-Cam</a> by hacksider and contributors (AGPL-3.0)</sub>
</p>

<p align="center">
  <img src="assets/icon/mirage-256.png" alt="Mirage icon" width="128">
</p>

<p align="center">
  <img src="docs/images/mirage-photos.jpg" alt="The Mirage window in Photos &amp; videos mode: the faces in a photo are marked A, B and C, and one of them gets a face from the library on the right" width="900">
</p>

Mirage is a small macOS app for real-time face swapping. Pick a photo, press
**Start**, and in Zoom or Meet you show up as your friend (who said yes), a
generated stranger, or yourself again with one key. It can also swap faces
in the photos and videos you already have.

It is a hobby project, a macOS-native app with Apple's Liquid Glass look. The
face swap itself comes from the excellent open-source
[Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam) engine by hacksider
and contributors: face detection, the swap model and the enhancers are theirs.
Mirage includes a copy of that engine (in
[`third_party/deep-live-cam/`](third_party/deep-live-cam/README.md), with a
few fixes) and builds everything else around it: the window, the face
library, Photos & videos, the virtual camera output and a pile of stability
fixes.

> [!IMPORTANT]
> **Consent first.** Only use someone else's face if they are fine with it, and
> tell people in the call (or whoever sees a swapped photo or video) that it
> is a joke. Mirage is for personal, non-commercial fun: the face models it
> relies on are licensed for non-commercial use only. Please read
> [Responsible use](docs/RESPONSIBLE_USE.md) (it is short).

## What it does

- **One window, Liquid Glass.** A live preview stage and one big Start/Stop
  button. The stage, the sidebar and the control bar sit on native macOS
  glass (`NSGlassEffectView`) that refracts a soft glow of your own video.
- **A face library.** Drag photos onto the sidebar (iPhone HEIC photos work
  too). Faces show up as big round thumbnails. Click one or press `1`–`9` to
  switch instantly (the face embeddings are cached, so nothing has to be
  detected again). `0` (the *Me* tile) gives you your real face back, 🎲 gives
  you a random generated one.
- **Photos and videos too.** Switch to **Photos & videos** in the title bar and
  drop in a photo, a whole folder or a video. Mirage finds the faces, swaps
  you (or the main face) at full resolution and saves the result next to the
  original. See [Photos & videos](#photos--videos).
- **Simple controls** in the *Look* section. Quality presets
  **Fast / Balanced / Best** (Best adds face enhancement), *Keep my mouth*
  (your real mouth stays in the picture, so talking looks natural), a
  *Strength* slider and a *Sharpness* slider. Under **More options**:
  *Swap everyone in view* (every face in the picture gets the one you picked),
  *Fix blue tint*, *Smooth edges* and *Show fps*. In Photos & videos the
  section shows only what changes a file: *Strength*, *Sharpness*,
  *Keep my mouth* and *Smooth edges*.
- **Made for calls.** Video goes straight to **OBS Virtual Camera** at a fixed
  1280×720, so Zoom never sees the stream restart when your webcam switches
  between 4:3 and 16:9. It keeps working with the window minimised, and keeps
  your Mac awake while you are live.
- **Starts and quits cleanly.** Only one copy runs (launching it again just
  brings the window forward). Quitting always releases the camera and stops
  every thread, even in the middle of a call.
- **A real app.** `Mirage.app` with its own icon, in English and Russian.
- **Fast on Apple Silicon.** About 14 fps live on a MacBook Air M1. The swap
  model runs on the Apple Neural Engine (about 63 ms per frame, versus about
  82 ms with the default CoreML setting), while face detection runs on the GPU
  in its own thread, so the two work at the same time. The live detector looks
  at a 320-pixel picture: about 9 ms instead of 26 ms at 640.

## Requirements

| | |
|---|---|
| macOS | 14 or newer recommended. The Liquid Glass look needs macOS 26+; older versions get a plain dark window. |
| Mac | Apple Silicon (M1 or newer) is required; the installer stops on Intel Macs. |
| Disk | About 4 GB free (Python environment and models), plus about 1 GB for Photos & videos (ffmpeg, and the photo face enhancer, downloaded the first time you use it). |
| Tools | [Homebrew](https://brew.sh) and the Xcode Command Line Tools (`xcode-select --install`). |
| Videos | [ffmpeg](https://ffmpeg.org), which `make install` installs with Homebrew. Photos and Live work without it. |
| Virtual camera | [OBS Studio](https://obsproject.com) (free). Mirage only borrows its virtual camera; no scenes or sources to set up. |

## Install

```bash
git clone https://github.com/RebSem/mirage
cd mirage
make install
```

`make install` runs `scripts/install.sh`: it installs Python 3.14 and ffmpeg
with Homebrew (if you don't have them yet), creates a virtual environment,
installs the Python packages, downloads the models and offers to install
OBS. It is safe to run again; finished steps are skipped.

The **Best** preset adds a face enhancer, GPEN-BFR-256 (about 75 MB). Mirage
downloads it the first time you choose Best; to get it ahead of time, run
`scripts/install.sh --with-enhancer`. If it can't be loaded, Mirage switches
Quality back to **Balanced** and tells you.

Then either run Mirage straight from the checkout:

```bash
make run
```

or build a proper app (`dist/Mirage.app`) and put it in `~/Applications`:

```bash
make install-app
```

`make install-app` also puts a `Mirage.app` shortcut in the project folder,
next to the code, so you can start Mirage from there as well as from
Launchpad or Spotlight. `Mirage.app` runs the code in the folder you cloned,
so don't move or delete that folder. If you do move it, run
`make install-app` again from the new place.

The first time you press Start, Mirage asks macOS for camera access and waits
for your answer. Click **Allow** (said no by accident? See
[Troubleshooting](docs/TROUBLESHOOTING.md#mirage-cant-use-the-camera)). If the
virtual camera does not show up in Zoom yet, open OBS and click
**Start Virtual Camera** once to install its system extension (details in
[Troubleshooting](docs/TROUBLESHOOTING.md#obs-virtual-camera-is-missing)).

## Use it in Zoom (or Meet, or anything else)

<p align="center">
  <img src="docs/images/mirage-live.jpg" alt="Mirage live: the camera picture with the chosen face, the red Stop button, and the face library on the right" width="900">
</p>

1. Open Mirage and pick a face (or `0` to stay yourself for now).
2. Press **Start** (or `Space`). Wait for *Live*.
3. In Zoom → **Settings → Video → Camera**, choose **OBS Virtual Camera**.
   In Google Meet and other apps it is the same idea: pick
   *OBS Virtual Camera* as your camera.
4. Switch faces during the call with `1`–`9`. Press `0` to be yourself again.

Do not press *Start Virtual Camera* inside OBS while Mirage is live: only one
app can feed the virtual camera. If Zoom shows the OBS logo instead of you,
Mirage is not live yet, or its frames are not getting through (see
[Troubleshooting](docs/TROUBLESHOOTING.md#zoom-shows-the-obs-logo-or-a-black-picture)).

## Photos & videos

Mirage can also swap faces in photos and videos you already have. Click
**Photos & videos** at the top of the window (**Live** takes you back; a call
in progress keeps going, with fewer frames per second while Mirage works on a
file). Your faces and the *Look* settings on the right work in both modes, but
each mode remembers its own selected face: picking faces for a photo never
changes the face you wear in a running call.

1. **Open** photos or a video: click **Open…** (or anywhere in the empty
   drop zone), press `⌘⇧O`, or drag files or a folder onto the stage. Photos
   dropped on the sidebar are added to your faces instead.
2. **Check who gets swapped.** Faces are marked with letters (A, B, C… from
   left to right), and the face selected on the right goes to one person:
   you, if one of your faces is marked **This is me** (right-click it) and
   you are in the picture; otherwise the main face, that is the largest one
   (or, of two about the same size, the one nearer the centre). Everyone else
   is left as is. A face that will be swapped gets a solid outline and a chip
   with its new face; a face left as is only gets four corner marks.
3. **Change it with a click.** Click a face in the picture (hovering shows
   *Choose a face…*) to choose who it becomes, or *Leave as is*. The most
   natural-looking choices (same gender, similar age) come first, and ★ marks
   a good match. With several faces, the button with two people
   (*Give everyone Anna’s face*) swaps them all.
4. **Swap**, then **Save** (`⌘S`); the big button always shows the next step
   (and says *Pick a face on the right* while nobody is set to be swapped).
   Hold the compare button (or `Space`) to compare with the original.

The result is saved next to the original as `name-mirage.jpg` (in the
original's format; iPhone HEIC photos become JPEG). The original is never
changed or overwritten: if the name is taken, you get `name-mirage-2.jpg`.
EXIF data such as the date and the place is kept, and the file notes that its
faces were swapped with Mirage.

**Many photos at once.** Drop several photos or a folder, then press
**Swap in N photos**. Each photo gets the automatic choice from step 2 and
is saved next to its original; the list shows how far it got and what
happened to each photo. Photos without a face are marked *No face*;
**Cancel** stops after the current photo, and **Continue · N left** picks up
where it stopped.

**Videos.** Open a video (MP4, MOV, M4V, MKV, AVI or WebM), check who gets
swapped on the frame Mirage shows, and press **Make video**. You see the
progress and the time left; **Cancel** deletes the unfinished file. When it
is done, **Play video** opens it and the folder button shows it in Finder.
The result, `name-mirage.mp4`, keeps the original sound and frame rate, and
iPhone HDR videos come out in standard (SDR) colour. People are followed by
who they are, not where they are, so the right face stays on the right
person. A 720p video renders at about 13–14 frames per second on a MacBook
Air M1. Videos need ffmpeg, which `make install` installs.

**Enhance faces** restores detail on the swapped faces. For photos it is on
by default, and a swap with it takes about half a second per face (its model,
GFPGAN, is downloaded the first time). For videos it is much slower, so it
starts off.

The details (how Mirage decides, renders and saves) are in
[docs/MEDIA.md](docs/MEDIA.md).

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Start / Stop. In Photos & videos: hold to compare with the original |
| `1` – `9` | Switch to face 1–9. In Photos & videos: every face being swapped gets it (or only the face you clicked) |
| `0` | Your real face. In Photos & videos: swap nobody (or leave the face you clicked as is) |
| `Esc` | In Photos & videos: deselect the face you clicked |
| `⌘O` | Add photos to your faces |
| `⌘⇧O` | Open photos or a video in Photos & videos |
| `⌘S` | Save the swapped photo |
| `⌘R` | Random face |
| `⌘⇧M` | Mirror the preview (the call is never mirrored) |
| `⌘Q` | Quit |

## Tips for a convincing swap

- Use a sharp, front-facing, evenly lit photo, one face per picture.
- Light your own face from the front; a window behind you makes everything
  harder.
- On a MacBook Air, plug in the charger and start with **Fast**. The Air has no
  fan and slows down when it gets hot.
- Turn on *Keep my mouth* if the mouth looks rubbery while you talk.

More in [Troubleshooting](docs/TROUBLESHOOTING.md).

## Your data stays on your Mac

Everything is processed locally: your camera feed, photos and videos never
leave the machine. The only network use is downloading the models (during
install, the first time you choose **Best** or enhance faces in a photo or
video, or later if one is missing) and fetching a generated face from
thispersondoesnotexist.com when you press 🎲.

| What | Where |
|---|---|
| Faces and settings | `~/Library/Application Support/Mirage` |
| Swapped photos and videos | next to the originals (`name-mirage.jpg`, `name-mirage.mp4`) |
| Logs | `~/Library/Logs/Mirage` |

To start from scratch, quit Mirage and delete
`~/Library/Application Support/Mirage`.

## The classic Deep-Live-Cam window

Deep-Live-Cam's own window comes with the engine and still works. Mirage
handles calls, photos and videos itself; the classic window is there for face
mapping and its other options:

```bash
make classic        # or: venv/bin/python third_party/deep-live-cam/run.py --execution-provider coreml
```

How to use it is described in the
[Deep-Live-Cam README](https://github.com/hacksider/Deep-Live-Cam/blob/759e3f985811985cf6c00a3e43e9579652c318f5/README.md)
for the version Mirage includes. What Mirage changed in the engine is listed
in [third_party/deep-live-cam/README.md](third_party/deep-live-cam/README.md).

## Project layout

```
mirage/                      the Mirage app: window, face library, Live, Photos & videos
third_party/deep-live-cam/   the face-swap engine: Deep-Live-Cam, with Mirage's fixes
scripts/                     installer, app bundle, icon, benchmark, engine update
tests/mirage/                Mirage's unit tests (no models, camera or network needed)
docs/                        documentation
assets/icon/                 the app icon
models/                      downloaded models (make install fills it; not in git)
Mirage.app                   shortcut to the installed app, made by make install-app (not in git)
```

Mirage's own code is in `mirage/`. The engine is Deep-Live-Cam as of upstream
commit `759e3f9`, with a few changes; [its README](third_party/deep-live-cam/README.md)
says what Mirage changed and how to bring in newer upstream versions
(`scripts/update_engine.sh`).

## Project docs

- [Troubleshooting](docs/TROUBLESHOOTING.md): camera permission, virtual
  camera, low fps, photos and videos, install errors, the face library, logs.
- [Photos & videos](docs/MEDIA.md): who gets swapped, how photos and videos
  are rendered and saved, speed on an M1.
- [Responsible use](docs/RESPONSIBLE_USE.md): the ground rules.
- [Design](docs/DESIGN.md): how the Liquid Glass window is put together.
- [Architecture](docs/ARCHITECTURE.md): threads, modules, file layout.
- [Engine](third_party/deep-live-cam/README.md): where the Deep-Live-Cam
  engine comes from, what Mirage changed in it, how to update it.
- [Contributing](CONTRIBUTING.md) and the [changelog](CHANGELOG.md).
- [Notice](NOTICE.md): the license notice for the included engine,
  third-party licenses, model terms.

## Contributing

Bug reports and small pull requests are very welcome. This is a spare-time
project, so replies may be slow, but they will come. See
[CONTRIBUTING.md](CONTRIBUTING.md) for how to run the tests and where things
live.

## Credits

- [Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam) by
  [hacksider](https://github.com/hacksider) and
  [all its contributors](https://github.com/hacksider/Deep-Live-Cam/graphs/contributors),
  itself based on [roop](https://github.com/s0md3v/roop) by s0md3v. Mirage
  would not exist without them.
- [InsightFace](https://github.com/deepinsight/insightface) for face detection,
  recognition and the swap model.
- [GPEN](https://github.com/yangxy/GPEN) for the face enhancement in **Best**
  and in videos (GPEN-BFR-256, converted to ONNX by
  [Face-Upscalers-ONNX](https://github.com/harisreedhar/Face-Upscalers-ONNX)).
- [GFPGAN](https://github.com/TencentARC/GFPGAN) for the face enhancement in
  photos.
- [FFmpeg](https://ffmpeg.org) for reading and writing videos.
- [This Person Does Not Exist](https://thispersondoesnotexist.com) for the
  generated faces behind 🎲.
- [OBS Studio](https://obsproject.com) and
  [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) for the virtual
  camera.
- [Qt for Python](https://doc.qt.io/qtforpython-6/),
  [ONNX Runtime](https://onnxruntime.ai) and [OpenCV](https://opencv.org).

## License

Mirage is free software under the [GNU AGPL-3.0](LICENSE). It includes a
modified copy of the Deep-Live-Cam engine (AGPL-3.0, in
[`third_party/deep-live-cam/`](third_party/deep-live-cam/README.md)), so the
whole app is under the same license. The pretrained face models come with
their own terms (InsightFace models are for non-commercial research use
only), which is why Mirage is a just-for-fun, non-commercial project. See
[NOTICE.md](NOTICE.md) for the full picture.

Mirage is not affiliated with Apple, Zoom, Google, OBS or the Deep-Live-Cam
team.
