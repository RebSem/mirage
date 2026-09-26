# Troubleshooting

Something not working? Find your symptom below. If nothing here helps, the
[logs](#where-the-logs-are) usually say why, and an
[issue](https://github.com/RebSem/mirage/issues/new/choose) with the log
attached is the fastest way to get help.

- [Mirage can't use the camera](#mirage-cant-use-the-camera)
- [OBS Virtual Camera is missing](#obs-virtual-camera-is-missing)
- [Zoom shows the OBS logo or a black picture](#zoom-shows-the-obs-logo-or-a-black-picture)
- [Low fps, choppy video](#low-fps-choppy-video)
- [“No face found” in a photo](#no-face-found-in-a-photo)
- [“Looking for your face…” while live](#looking-for-your-face-while-live)
- [The wrong camera is used](#the-wrong-camera-is-used)
- [Install problems](#install-problems)
- [Where the logs are](#where-the-logs-are)
- [Reset or uninstall](#reset-or-uninstall)

## Mirage can't use the camera

You see *“The camera didn't start”* or the preview stays empty.

1. Open **System Settings → Privacy & Security → Camera** and turn on
   **Mirage**.
2. If you started Mirage from a terminal (`make run`), macOS asks on behalf of
   the terminal app, so turn on **Terminal** (or iTerm, or whatever you use)
   instead.
3. Quit and reopen Mirage after changing the setting.
4. If it still fails, quit other apps that use the webcam (Zoom, FaceTime,
   Photo Booth) or switch them to *OBS Virtual Camera*, then press Start
   again.

## OBS Virtual Camera is missing

Zoom has no *OBS Virtual Camera* in its list, or Mirage says *“OBS Virtual
Camera isn't installed”*.

The virtual camera is a macOS system extension that OBS installs the first
time you use it. You only need to do this once:

1. Install [OBS Studio](https://obsproject.com) if you have not
   (`brew install --cask obs` works too). Use OBS 30 or newer.
2. Open OBS and click **Start Virtual Camera** (bottom right).
3. macOS asks to allow the extension. Go to **System Settings → General →
   Login Items & Extensions** and allow OBS under camera extensions. You may
   need to enter your password.
4. Click **Stop Virtual Camera** and quit OBS. From now on Mirage drives the
   virtual camera on its own; OBS does not need to be open.
5. Restart Zoom (or reload the Meet tab) so it notices the new camera.

## Zoom shows the OBS logo or a black picture

That placeholder means nothing is feeding the virtual camera: **Mirage is not
live**. Press **Start** (or `Space`) in Mirage and wait for *Live*.

If Mirage is live and Zoom still shows the logo:

- Make sure OBS itself is **not** running its own virtual camera. Only one
  app can feed it; click *Stop Virtual Camera* in OBS or quit OBS.
- In Zoom → **Settings → Video → Camera**, pick another camera and then
  *OBS Virtual Camera* again.

## Low fps, choppy video

On a MacBook Air M1, 10–15 fps live is normal. If you get less:

- Choose the **Fast** preset. **Best** adds face enhancement, which is the
  most expensive step; keep it off unless you really need it.
- Plug in the charger and turn off Low Power Mode.
- Close heavy apps: browsers with many tabs, other video apps, games,
  anything exporting video.
- Let it breathe. The MacBook Air has no fan and slows down when it gets hot;
  keep it on a hard surface, not a blanket or your lap.
- Turn on *Show FPS* (under **More**) to see the effect of each change.

## “No face found” in a photo

Mirage needs a clear face in each photo you add (if there are several, it
takes the largest). Use a photo that is:

- **front-facing**: looking roughly at the camera, not in profile;
- **well lit**: no harsh shadows, not backlit;
- **sharp**: no motion blur, not a tiny face in a big group shot;
- **uncovered**: no sunglasses, masks or hands over the face.

If the photo has several people, crop it to the one you want first. Very
close-up portraits are fine.

## “Looking for your face…” while live

Mirage cannot see your face on the camera right now. Face the camera, light
your face from the front (a bright window behind you is the usual culprit)
and move back a little if you are very close. The swap follows the largest
face in view, so it will ignore a poster behind you.

## The wrong camera is used

Pick your camera in Mirage's **Camera** setting. Mirage remembers the choice
by the camera's ID, so an iPhone with Continuity Camera turning up later does
not steal the slot. OBS Virtual Camera is never offered as an input, because
Mirage writes to it.

## Install problems

`make install` is safe to run again at any time; it skips whatever is
already done. Try that first.

### insightface: “unknown architecture arm64e”

insightface is compiled during install. When `xcode-select` points at an Xcode
that is older than your macOS SDK, the link step fails with
`unknown architecture arm64e`. `scripts/install.sh` already works around this
by building with the standalone Command Line Tools. If you install packages by
hand, do the same:

```bash
xcode-select --install   # if the Command Line Tools are missing
DEVELOPER_DIR=/Library/Developer/CommandLineTools \
  venv/bin/python -m pip install -r requirements.txt
```

### The venv broke after a Homebrew update

When Homebrew upgrades Python, an existing virtual environment can stop
working. Run `make install` again: it moves the broken `venv` aside
(`venv.broken-<date>`) and builds a fresh one. Delete the old folder once
everything works.

### Model download failed

Check your connection and run `make install` again; downloads pick up where
they stopped. If Mirage says *“Models are missing”*, the same command fixes
it.

### “Face enhancement isn't available”

The **Best** preset needs the optional face enhancer model. Download it with:

```bash
scripts/install.sh --with-enhancer
```

## Where the logs are

Mirage writes its logs to `~/Library/Logs/Mirage`. Open the folder with
**Help → Show Logs**, or from a terminal:

```bash
open ~/Library/Logs/Mirage
```

When you attach a log to an issue, skim it first; it can contain file names
from your Mac.

## Reset or uninstall

**Reset** (start with an empty face library and default settings): quit
Mirage, then delete `~/Library/Application Support/Mirage`. This removes your
imported faces for good; move it to the Trash instead if you might want them
back.

```bash
rm -rf ~/Library/Application\ Support/Mirage
```

**Uninstall completely:**

1. Quit Mirage and delete `~/Applications/Mirage.app` (if you installed it).
2. Delete the `mirage` folder you cloned (it holds the venv and the models).
3. Delete `~/Library/Application Support/Mirage` and `~/Library/Logs/Mirage`.
4. Delete `~/.insightface/models/buffalo_l` (the face detection models).
5. Optionally, uninstall OBS and remove Mirage under **System Settings →
   Privacy & Security → Camera**.
