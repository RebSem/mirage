# Troubleshooting

Something not working? Find your symptom below. If nothing here helps, the
[logs](#where-the-logs-are) usually say why, and an
[issue](https://github.com/RebSem/mirage/issues/new/choose) with the log
attached is the fastest way to get help.

- [Mirage can't use the camera](#mirage-cant-use-the-camera)
- [OBS Virtual Camera is missing](#obs-virtual-camera-is-missing)
- [Zoom shows the OBS logo or a black picture](#zoom-shows-the-obs-logo-or-a-black-picture)
- [“Nothing is reaching OBS Virtual Camera”](#nothing-is-reaching-obs-virtual-camera)
- [Low fps, choppy video](#low-fps-choppy-video)
- [“No face found” in a photo](#no-face-found-in-a-photo)
- [“Looking for your face…” while live](#looking-for-your-face-while-live)
- [The wrong camera is used](#the-wrong-camera-is-used)
- [Face names reset to “Face”](#face-names-reset-to-face)
- [Photos & videos](#photos--videos): [ffmpeg](#videos-need-ffmpeg),
  [no faces found](#no-faces-found-here),
  [the wrong person swapped](#the-wrong-person-got-swapped),
  [the first photo is slow](#the-first-photo-takes-a-while),
  [slow videos](#making-a-video-is-slow-or-the-mac-gets-warm),
  [washed-out videos](#the-video-looks-washed-out),
  [no sound](#the-video-has-no-sound),
  [where the results are](#where-are-my-results)
- [Install problems](#install-problems)
- [Where the logs are](#where-the-logs-are)
- [Reset or uninstall](#reset-or-uninstall)

## Mirage can't use the camera

The first time you press **Start**, Mirage asks macOS for camera access and
waits for your answer. Click **Allow** and it goes live.

If you clicked *Don't Allow*, Mirage says *“Mirage isn't allowed to use the
camera”*. To change your mind:

1. Open **System Settings → Privacy & Security → Camera** and turn on
   **Mirage**.
2. If you started Mirage from a terminal (`make run`), macOS asks on behalf of
   the terminal app, so turn on **Terminal** (or iTerm, or whatever you use)
   instead.
3. Press **Start** again. If Mirage still says no, quit and reopen it.

If you see *“The camera didn't start”* or the preview stays empty, quit other
apps that use the webcam (Zoom, FaceTime, Photo Booth) or switch them to
*OBS Virtual Camera*, then press Start again. If you have more than one
camera, also check that the right one is picked (see
[The wrong camera is used](#the-wrong-camera-is-used)).

If Mirage stops on its own and says *“The camera stopped sending video”*, the
camera sent nothing for 5 seconds; for example, it was unplugged or another
app took it over. Shorter gaps don't stop Mirage. Press **Start** again once
the camera is back.

## OBS Virtual Camera is missing

Zoom has no *OBS Virtual Camera* in its list, or Mirage's top bar says
*“OBS Virtual Camera isn't installed”*.

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

That placeholder means nothing is feeding the virtual camera. Usually
**Mirage is not live**: press **Start** (or `Space`) in Mirage and wait for
*Live*.

If Mirage is live and Zoom still shows the logo, look at Mirage's top bar:

- *“Sending to OBS Virtual Camera”*: frames are going out, so Zoom just has
  not caught up. In Zoom → **Settings → Video → Camera**, pick another camera
  and then *OBS Virtual Camera* again, or restart Zoom.
- *“Nothing is reaching OBS Virtual Camera”*: see the next section.

### “Nothing is reaching OBS Virtual Camera”

Mirage shows this in its top bar (with a short toast) when it has been live
for a few seconds but still can't connect to OBS Virtual Camera, so no
frames reach the call. Your preview keeps working; only the call misses out.
Usually it is one of these:

- **OBS is running its own virtual camera.** Only one app can feed it; click
  *Stop Virtual Camera* in OBS or quit OBS.
- **The OBS camera extension is not installed or not allowed.** Follow
  [OBS Virtual Camera is missing](#obs-virtual-camera-is-missing).

Mirage keeps trying every few seconds, so once that is fixed the top bar
usually switches to *“Sending to OBS Virtual Camera”* on its own. If it does
not, press **Stop** and **Start** again.

## Low fps, choppy video

On a MacBook Air M1, about 14 fps live is normal (fewer with **Best**). If
you get less:

- Choose the **Fast** preset. **Best** adds face enhancement, which is the
  most expensive step; keep it off unless you really need it.
- Turn off *Swap everyone in view* (under **More**) unless you need it; every
  extra face in the picture costs another swap.
- Plug in the charger and turn off Low Power Mode.
- Close heavy apps: browsers with many tabs, other video apps, games,
  anything exporting video.
- Let it breathe. The MacBook Air has no fan and slows down when it gets hot;
  keep it on a hard surface, not a blanket or your lap.
- Don't make a video or run a batch in **Photos & videos** during a call:
  both use the Neural Engine, so the call gets fewer fps while they run.
- Turn on *Show FPS* (under **More**) to see the effect of each change.

## “No face found” in a photo

This is about adding a face to your gallery. For photos opened in
**Photos & videos**, see [“No faces found here”](#no-faces-found-here).

Mirage needs a clear face in each photo you add (if there are several, it
takes the largest). Use a photo that is:

- **front-facing**: looking roughly at the camera, not in profile;
- **well lit**: no harsh shadows, not backlit;
- **sharp**: no motion blur, not a tiny face in a big group shot;
- **uncovered**: no sunglasses, masks or hands over the face.

If the photo has several people, crop it to the one you want first. Very
close-up portraits are fine.

If Mirage says the file *isn't an image Mirage can read*, open it in Preview
and export it as JPEG or PNG. JPEG, PNG, WebP, BMP, TIFF and iPhone HEIC
photos all work.

## “Looking for your face…” while live

Mirage cannot see your face on the camera right now. Face the camera, light
your face from the front (a bright window behind you is the usual culprit),
and move back a little if you are very close, or closer if you sit far away.
The swap follows the largest face in view, so it will ignore a poster behind
you.

## The wrong camera is used

Pick your camera in the menu at the bottom left of Mirage's window, next to
the camera icon (you can change it while Mirage is not live). The list is
refreshed every time you open it. Mirage remembers the choice by the
camera's ID, so an iPhone with Continuity Camera turning up later does not
steal the slot. OBS Virtual Camera is never offered as an input, because
Mirage writes to it.

## Face names reset to “Face”

Mirage keeps the list of your faces in `faces/index.json` inside
`~/Library/Application Support/Mirage`. If that file gets damaged (say, a
crash or a full disk at the wrong moment), Mirage rebuilds the list from the
saved face files the next time it starts. Your faces come back, in the order
you added them, but their names reset to *Face*: right-click a face and
choose **Rename…** to fix them. The damaged file is kept in the same folder
as `faces/index.corrupt-<time>.json`, in case you want to copy the old names
from it.

If the saved data of a single face is damaged, Mirage shows your real face
instead and tells you; remove that face and add its photo again.

## Photos & videos

How the mode decides and saves is described in [MEDIA.md](MEDIA.md).

### “Videos need ffmpeg”

Mirage reads and writes videos with ffmpeg. `make install` installs it with
Homebrew; if that step was skipped or failed, run `make install` again or
install it yourself:

```bash
brew install ffmpeg
```

There is no need to restart Mirage: it looks for ffmpeg every time you open
a video, in Homebrew's folders as well as on your `PATH`. Photos and Live
work without ffmpeg.

### “No faces found here”

Mirage searched the whole photo and found no face. It finds faces that are:

- **big enough**: a tiny face in a wide group shot can be missed. On large
  photos Mirage takes a second, closer look for small faces, so the
  full-size original works better than a shrunk copy (for example one saved
  from a messenger). Try a bigger photo;
- **turned towards the camera**: profiles and strongly angled faces are hard
  to find;
- **uncovered**: no sunglasses, masks or hands over the face.

For a video, Mirage looks for faces in 8 frames spread over the clip and
shows the best one. If nobody faces the camera in any of them, trim the clip
to the part where people are clearly visible.

### The wrong person got swapped

By default Mirage swaps you, if one of your faces is marked **This is me**
and you are in the picture; otherwise the largest face (of two about the
same size, the one nearer the centre). To change that:

- **Click a face in the picture** and pick who it becomes; pick
  **Leave as is** for anyone who should stay as they are.
- **Mark yourself.** Right-click your own face in the gallery on the right
  and choose **This is me**. From then on Mirage looks for you first in
  photos, batches and videos. If it still misses you (very different light,
  angle or age), add a clearer photo of yourself and mark that one.
- **Batches** always use the automatic choice. To fix single photos, open
  them one at a time.
- **Videos** follow people by their faces, starting from the frame Mirage
  shows. People who look very much alike, or faces that are small or turned
  away, can still be mixed up in places.

### The first photo takes a while

The first time you open a photo, finding faces takes about 10 seconds while
the models load, and the first **Swap** another 4–7 seconds while the face
enhancer (GFPGAN) loads. The very first time, the enhancer is also
downloaded (about 370 MB). After that, finding faces takes well under a
second, and swapping about half a second per face on a MacBook Air M1.
Switching back to **Live** frees the enhancer's memory, so the next swap
after that loads it again.

### Making a video is slow, or the Mac gets warm

That is expected: every face in every frame goes through the swap model. On
a MacBook Air M1, a 720p video with one face renders at about 13–14 frames
per second (a one-minute clip at 30 fps takes a bit over two minutes), and
with two people at about 10. To go faster:

- Plug in the charger. A fanless Air slows down as it heats up; the time
  left adjusts as it goes.
- Stop **Live**. A call and a render share the Neural Engine, so both get
  slower.
- Leave **Enhance faces (slower)** off for videos.
- Close other heavy apps.

The Mac stays awake while a video renders, so you can leave it running, and
it is normal for it to get warm.

### The video looks washed out

iPhone videos are usually HDR. Mirage converts them to standard (SDR) colour
on the Mac's video hardware (VideoToolbox). If that conversion can't be used
for a file, Mirage falls back to plain decoding and the result looks pale and
flat. Please [open an issue](https://github.com/RebSem/mirage/issues/new/choose)
with the [log](#where-the-logs-are) attached and, if you can, say which phone
or camera recorded the clip.

### The video has no sound

Mirage copies the original's sound, or converts it to AAC when an MP4 file
can't hold it as it is. If even that fails, the video is saved without sound
and the [log](#where-the-logs-are) says why. Check that the original has
sound in the first place.

### Where are my results?

Next to the originals, in the same folder: `name-mirage.jpg` for a photo (in
the original's format; HEIC becomes JPEG) and `name-mirage.mp4` for a video,
with `-2`, `-3` and so on if you swap the same file again. **Show in Finder**
selects the file. Originals are never modified or overwritten.

A single photo is saved only when you press **Save** (`⌘S`); a batch and a
video save each result as soon as it is ready. If saving fails (for
example, the folder is on a read-only disk), copy the originals to a folder
you can write to, such as *Pictures*, and try again.

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

Downloads check the server's security certificate. A certificate error
(`CERTIFICATE_VERIFY_FAILED`) means something on your network, such as a
company proxy or antivirus software, is intercepting the connection; try
another network.

### “Face enhancement isn't available”

The **Best** preset uses the GPEN-BFR-256 face enhancer (about 75 MB), which
Mirage downloads the first time you choose Best. If it can't be downloaded or
loaded, Mirage switches Quality back to **Balanced** and says *“Face
enhancement isn't available; using Balanced”*, so your call carries on.

Check your connection and choose **Best** again; Mirage tries once more. Or
download the enhancer ahead of time:

```bash
scripts/install.sh --with-enhancer
```

The [logs](#where-the-logs-are) say what went wrong.

## Where the logs are

Mirage writes its logs to `~/Library/Logs/Mirage`: `mirage.log`, plus
`launcher.log` when you start `Mirage.app`. Open the folder with
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
5. Optionally, uninstall OBS, and ffmpeg too (`brew uninstall ffmpeg`) if
   nothing else of yours needs it, and turn Mirage off under
   **System Settings → Privacy & Security → Camera**.
