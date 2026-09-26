<p align="right"><b>English</b> · <a href="README.ru.md">Русский</a></p>

<h1 align="center">Mirage</h1>

<p align="center">
  Wear a different face on your video calls. Live, on your Mac, just for fun.
</p>

<p align="center">
  <img src="docs/images/mirage-hero.png" alt="The Mirage window: live video on the left, a glass sidebar of faces on the right, a big Start button below" width="860">
</p>

Mirage is a small macOS app for real-time face swapping. Pick a photo, press
**Start**, and in Zoom or Meet you show up as your friend (who said yes), a
generated stranger, or yourself again with one key.

It is a hobby project: a nicer, macOS-native frontend with Apple's Liquid Glass
look, built on top of the excellent open-source
[Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam) engine by hacksider
and contributors. The heavy lifting (face detection, the swap model, the
enhancers) is theirs. Mirage adds the window, the face library, the virtual
camera plumbing, and a pile of stability fixes.

> [!IMPORTANT]
> **Consent first.** Only use someone else's face if they are fine with it, and
> tell people in the call when it is a joke. Mirage is for personal,
> non-commercial fun: the face models it relies on are licensed for
> non-commercial use only. Please read [Responsible use](docs/RESPONSIBLE_USE.md)
> (it is short).

## What it does

- **One window, Liquid Glass.** A live preview stage and one big Start/Stop
  button. The sidebar and control bar are native macOS glass
  (`NSGlassEffectView`) that refracts a soft glow of your own video.
- **A face library.** Drag photos into the sidebar. Faces show up as big round
  thumbnails. Click one or press `1`–`9` to switch instantly (the face
  embeddings are cached, so there is no re-detection). `0` (the *Me* tile) gives
  you your real face back, 🎲 gives you a random generated one.
- **Simple controls.** Quality presets **Fast / Balanced / Best** (Best adds
  face enhancement), *Keep my mouth* (your own mouth stays visible, so talking
  looks natural), a blend slider and a sharpness slider.
- **Made for calls.** Video goes straight to **OBS Virtual Camera** at a fixed
  1280×720, so Zoom never sees the stream restart when your webcam changes
  shape. It keeps working with the window minimised, and keeps your Mac awake
  while you are live.
- **Starts and quits cleanly.** Only one copy runs (launching it again just
  brings the window forward). Quitting always releases the camera and stops
  every thread, even in the middle of a call.
- **A real app.** `Mirage.app` with its own icon, in English and Russian.
- **Uses the Neural Engine.** On a MacBook Air M1 the swap model takes about
  63 ms per frame on the Apple Neural Engine versus about 85 ms with the default
  CoreML setting, roughly a third more fps. Expect 10–15 fps live on an M1.

## Requirements

| | |
|---|---|
| macOS | 14 or newer recommended. The Liquid Glass look needs macOS 26+; older versions get a translucent fallback. |
| Mac | Apple Silicon recommended (M1 or newer). |
| Disk | About 3 GB (Python environment and models). |
| Tools | [Homebrew](https://brew.sh) and the Xcode Command Line Tools (`xcode-select --install`). |
| Virtual camera | [OBS Studio](https://obsproject.com) (free). Mirage only borrows its virtual camera; no scenes or sources to set up. |

## Install

```bash
git clone https://github.com/RebSem/mirage
cd mirage
make install
```

`make install` runs `scripts/install.sh`: it installs Python 3.14 with
Homebrew, creates a virtual environment, downloads the models and offers to
install OBS. It is safe to run again; finished steps are skipped.
The face enhancer used by the **Best** preset is an optional extra download
(about 350 MB): `scripts/install.sh --with-enhancer`.

Then either run Mirage straight from the checkout:

```bash
make run
```

or build a proper app (`dist/Mirage.app`) and put it in `~/Applications`:

```bash
make app && make install-app
```

The first time you press Start, macOS asks for camera access. Say yes. If the
virtual camera does not show up in Zoom yet, open OBS once and click
**Start Virtual Camera** once to install its system extension (details in
[Troubleshooting](docs/TROUBLESHOOTING.md#obs-virtual-camera-is-missing)).

## Use it in Zoom (or Meet, or anything else)

1. Open Mirage and pick a face (or `0` to stay yourself for now).
2. Press **Start** (or `Space`). Wait for *Live*.
3. In Zoom → **Settings → Video → Camera**, choose **OBS Virtual Camera**.
   In Google Meet and other apps it is the same idea: pick
   *OBS Virtual Camera* as your camera.
4. Switch faces during the call with `1`–`9`. Press `0` to be yourself again.

Do not press *Start Virtual Camera* inside OBS while Mirage is streaming; they
would fight over the same camera. If Zoom shows the OBS logo instead of you,
Mirage is not live yet.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Start / Stop |
| `1` – `9` | Switch to face 1–9 |
| `0` | Your real face |
| `⌘O` | Add photos |
| `⌘R` | Random face |
| `⌘M` | Mirror the preview (the call is never mirrored) |
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

All video processing happens locally; your camera feed never leaves the
machine. The only network use is downloading the models (during install, or
later if one is missing) and fetching a generated face when you press 🎲.

| What | Where |
|---|---|
| Faces and settings | `~/Library/Application Support/Mirage` |
| Logs | `~/Library/Logs/Mirage` |

To start from scratch, quit Mirage and delete the first folder.

## The classic Deep-Live-Cam UI

The original Deep-Live-Cam window is still here and still works, including the
things Mirage does not do (image and video files, face mapping, many faces):

```bash
make classic        # or: source venv/bin/activate && python run.py
```

Its original README is kept at [docs/upstream/README.md](docs/upstream/README.md).

## Project docs

- [Troubleshooting](docs/TROUBLESHOOTING.md): camera permission, missing virtual
  camera, low fps, install errors, logs.
- [Responsible use](docs/RESPONSIBLE_USE.md): the ground rules.
- [Design](docs/DESIGN.md): how the Liquid Glass window is put together.
- [Architecture](docs/ARCHITECTURE.md): threads, modules, file layout.
- [Contributing](CONTRIBUTING.md) and the [changelog](CHANGELOG.md).
- [Notice](NOTICE.md): what changed versus upstream, third-party licenses.

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
- [GFPGAN](https://github.com/TencentARC/GFPGAN) for face enhancement.
- [OBS Studio](https://obsproject.com) and
  [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) for the virtual
  camera.
- [Qt for Python](https://doc.qt.io/qtforpython-6/),
  [ONNX Runtime](https://onnxruntime.ai) and [OpenCV](https://opencv.org).

## License

Mirage is a modified version of Deep-Live-Cam and, like it, is licensed under
the [GNU AGPL-3.0](LICENSE). The pretrained face models come with their own
terms (InsightFace models are for non-commercial research use only), which is
why Mirage is a just-for-fun, non-commercial project. See [NOTICE.md](NOTICE.md)
for the full picture.

Mirage is not affiliated with Apple, Zoom, Google, OBS or the Deep-Live-Cam
team.
