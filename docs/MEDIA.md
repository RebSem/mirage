# Photos & videos mode

Swap faces in files you already have: one photo, a batch of photos, or a
video. Mirage finds the faces, decides who should become whom, lets you
correct that with a click, renders at full resolution and saves the result
next to the original. The original file is only ever read.

This page describes how the mode works, with the rules and numbers the code
uses. For a short how-to, see the
[README](../README.md#photos--videos); for problems, see
[Troubleshooting](TROUBLESHOOTING.md#photos--videos).

- [Opening files](#opening-files)
- [Finding faces](#finding-faces)
- [Who becomes whom](#who-becomes-whom)
- [On screen](#on-screen)
- [Rendering a photo](#rendering-a-photo)
- [Loading and saving photos](#loading-and-saving-photos)
- [Batch](#batch)
- [Videos](#videos)
- [Speed on a MacBook Air M1](#speed-on-a-macbook-air-m1)
- [Running well on M-series Macs](#running-well-on-m-series-macs)
- [Code map](#code-map)

## Opening files

The mode is a second page in the main window, picked with the
**Live | Photos & videos** switch in the middle of the title bar and
remembered between launches (`Settings.mode`). The face gallery and the
*Look* settings in the sidebar are shared with Live, and a live session keeps
running while you work on files. The title bar shows the call's status and
the virtual camera hint here only while a call is running in the background.

The *Look* section shows only the settings that change a file: *Strength*,
*Sharpness*, *Keep my mouth* and *Smooth edges*. The quality presets,
*Swap everyone in view*, *Fix blue tint* and *Show fps* only affect calls, so
they are hidden in this mode. Changing one of the four after a swap turns the
big button back into **Swap** (see [Changing the plan](#changing-the-plan)).

Files come in through **Open…** (the big button while nothing is open, the
`+` button once something is, `⌘⇧O`, *File → Open Photos or Video…*, or a
click anywhere in the empty drop zone) or a drop:

- Dropped on the **sidebar**: photos are added to the face gallery, as before.
- Dropped anywhere else in **Photos & videos**: opened in this mode.
- Dropped on the stage in **Live**: videos and folders switch to Photos &
  videos and open there; plain photos are added to the gallery as before.

`photo_io.collect_media()` sorts what arrived into photos and videos:

- Photos: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tif`, `.tiff`,
  `.heic`, `.heif`. Videos: `.mp4`, `.mov`, `.m4v`, `.mkv`, `.avi`, `.webm`.
- A folder contributes its direct children only (no subfolders), without
  hidden files and without earlier results (`*-mirage.*`, `*-mirage-N.*`).
  Files named explicitly are taken as they are.
- Duplicates (the same file through another path or letter case) are dropped,
  and both lists are sorted naturally by name (`img2` before `img10`).

Then: one photo opens as a photo, several photos (or a folder) as a batch,
one video as a video. Videos open one at a time: with a mix, the photos open
as a batch; with several videos, the first one opens; either way a toast says
*Videos open one at a time.* While a job is running, new files are refused
with *Wait for the current job to finish (or cancel it).*

## Finding faces

`analyze.analyze_image()` runs on a worker thread and returns every face as a
`TargetFace`: box, five landmarks, detector score, a 512-float identity
embedding, gender and age.

- **Detection** uses InsightFace's SCRFD detector (`det_10g.onnx` from
  `buffalo_l`) at 640×640 on the **CPU**, threshold 0.5. It is the same
  detector the face gallery uses for imports (`faces_ai._photo_detector()`),
  not Live's 320 px detector on the GPU. A photo is a one-off job, so the CPU
  is fast enough (about 0.1–0.4 s on an M1) and it never competes with a
  live session for the GPU or the Neural Engine.
- **Small faces:** if the photo's longest side is over 1400 px and either no
  face was found or the smallest one is narrower than 6 % of the image width,
  a second pass runs at 1280×1280. Both passes are merged with non-maximum
  suppression: highest score first, boxes overlapping a kept one by IoU ≥ 0.4
  are dropped.
- **Identity:** InsightFace's recognition model (ArcFace from `buffalo_l`)
  gives each face its embedding.
- **Gender and age:** `genderage.onnx` from `buffalo_l`, on the CPU. If it
  fails, both are left unknown; nothing else depends on them.
- **Order:** faces are numbered 1, 2, 3… from left to right by the centre
  of their box (top to bottom on a tie). On screen the same order is shown
  as letters, A, B, C… (`face_letter()` in `media_view.py`), so they never
  look like the gallery's `1`–`9` shortcuts; either way they are stable and
  easy to talk about.

The shared CPU detector is not re-entrant, so detection calls are serialised
with a lock.

For a **video**, Mirage probes the file, decodes 8 evenly spaced frames (at
1/16, 3/16, … of its length), analyses each like a photo and shows the one
with the largest face (on a tie, the one with more faces). The plan is made on
that frame; see [Videos](#videos) for how it carries over to the rest.

## Who becomes whom

A *plan* maps each face number to a library face id, or to nothing
(*Leave as is*). `plan.py` is pure numpy and fully unit-tested.

### The automatic plan

`auto_plan()` gives the face selected in the gallery to exactly one person.
Photos & videos keeps its own selection (`MediaPage.selected_id`, which starts
as Live's `Settings.face_id`), so choosing faces here never changes the face
you wear in a running call.

1. **Nothing selected** (the *Me* tile): nobody is swapped; a toast asks you
   to pick a face in the gallery first, and the big button says *Pick a face
   on the right*.
2. **Find me.** If a library face is marked *This is me*
   (`Settings.me_face_id`), the face in the picture with the highest cosine
   similarity to it is chosen, provided the similarity is at least **0.40**
   (`ME_THRESHOLD`). In other words: if you are in the picture, you are the
   one who gets the new face.
3. **Main face.** Otherwise the largest face by box area. Every face within
   **15 %** of the largest area (`NEAR_TIE`) counts as equally big, and among
   those the one whose centre is nearest to the centre of the image wins.
4. Everyone else is left as is.

*This is me* is set in the gallery: right-click a face and choose
**This is me** (or **This isn't me** to clear it). Only one face can be you.

### Changing the plan

- **Click a face** in the picture (hovering one shows a *Choose a face…*
  chip): a menu shows *Face B · man, about 34* (when gender and age are
  known), then **Leave as is**, then every library face, ranked (see below).
  The current choice is ticked.
- **Give everyone the selected face** (the people button, shown when there
  are two or more faces; its tooltip names the face, *Give everyone Anna’s
  face*): every face gets the selected library face (`swap_everyone()`).
- **A gallery click or `1`–`9`** while a face in the picture is highlighted
  changes only that face. Otherwise it changes the selected face: if anyone
  is being swapped, all of them get the new face; if nobody is, the automatic
  plan is made again with it. **`0`** (*Me*) leaves the highlighted face as
  is, or, with nothing highlighted, clears the plan. **`Esc`** removes the
  highlight.
- Any change after **Swap** throws the rendered result away; the stage shows
  the original again and the button goes back to **Swap**. That includes
  **Enhance faces** and the four *Look* settings (*Strength*, *Sharpness*,
  *Keep my mouth*, *Smooth edges*), because the result on screen was made
  with the old values.

### Suggestions

The list in the face menu is sorted by how natural each library face is
likely to look on that person (`suggestion_score()`):

```
score = 0.65 × gender + 0.35 × age
gender = 1.0 same, 0.2 different, 0.6 unknown
age    = exp(−|age difference| / 12 years), 0.7 unknown
```

Ties keep the gallery order. The top two, if they score at least **0.55**
(`SUGGEST_MIN`), are marked **★ good match**. Suggestions only order the
list; they never change the plan by themselves.

### Gender and age of library faces

- **New faces** get their gender and age at import: `faces_ai.embed()` runs
  `genderage.onnx` on the main face of the photo, and the library stores them
  in `faces/index.json` (`gender`: 1 = man, 0 = woman; `age`: years, 0–120,
  rounded to 0.1).
- **Faces added before this mode existed** have neither. They are filled in
  lazily: when a photo or video is opened in Photos & videos, the worker
  thread analyses the stored photo of every library face still missing its
  gender (largest face) and saves the result with
  `FaceLibrary.set_attributes()`. Each face is tried at most once per session,
  so only the first file you open after upgrading takes a moment longer.

## On screen

`MediaView` draws the picture fitted into the stage, with rounded corners,
and marks the plan on it:

- **Every face** has its letter in a small round badge on the top-left
  corner of its box.
- **Will be swapped:** a solid outline with a violet-to-blue gradient, the
  badge filled violet, and a chip with the new face's avatar and name.
- **Left as is:** four corner marks and a dark badge, no chip. Hovering
  brightens the marks and shows a quiet *Choose a face…* chip. The face you
  clicked glows while its menu is open, and stays highlighted if you close
  the menu without choosing.
- **Chips** stay inside the photo and never cover each other: each one goes
  under its face if there is room, otherwise inside the bottom of the
  outline or above the face.
- **After a swap** a chip labels the photo, above it when there is room and
  on its top-left corner otherwise: *Swapped · hold Space to compare*. While
  you hold the compare button or `Space` it says *Original* and the marks are
  hidden, so you see the original clean.
- **While Mirage works**, the marks are hidden, the photo dims and a small
  capsule with a spinner in its middle says what is happening (*Finding
  faces…*, *Swapping faces…*, or *Downloading face enhancement (about 370 MB,
  first time only)…*); for a video it adds a progress bar (see
  [Videos](#videos)).
- **Nothing open:** the whole dashed drop zone is clickable and opens files,
  with the hint *Pick who to become on the right · ⌘⇧O opens files*.

The big button in the control bar always shows the next step and never
offers something that can't be done:

| State | The big button reads |
|---|---|
| nothing open | **Open…** |
| a photo | *Finding faces…* → **Swap** → *Swapping faces…* → **Save** → *Saving…* → **Show in Finder** |
| several photos or a folder | **Swap in N photos** → **Cancel** (while it runs) → **Show in Finder** (**Continue · N left** after a cancel, **Open another…** if nothing was saved) |
| a video | *Finding faces…* → **Make video** → **Cancel** (while it runs) → **Play video** |
| no faces found | **Open another…** |
| faces found, but nobody to swap (for example with *Me* selected) | *Pick a face on the right*, muted; clicking it explains in a toast |

*Finding faces…*, *Swapping faces…* and *Saving…* show a spinner and can't
be clicked. The other buttons in the bar follow the same rule: `+` (open) is
there only once something is open, the people button only with two or more
faces, compare only after a photo swap, and the folder button
(**Show in Finder**) only where the big button says something else: after a
video (**Play video**) or after a cancelled batch that saved some photos
(**Continue · N left**).

## Rendering a photo

`render.PhotoRenderer.render()` works on the full-resolution photo; nothing is
scaled down.

1. For every face with a library face in the plan, an InsightFace `Face` is
   built from the stored box and landmarks.
2. With *Keep my mouth* on, the mouth landmarks are computed on the
   **original** photo, so the real mouth comes from the original even when
   faces are close together and one is already swapped.
3. `face_swapper.swap_face()` swaps it: inswapper_128 on the Neural Engine,
   pasted back into the full-size photo. The *Look* settings apply as in
   Live: *Strength*, *Keep my mouth*, *Smooth edges* and, afterwards,
   *Sharpness* on the swapped boxes.
4. With **Enhance faces** on (`Settings.photo_enhance`, the default), GFPGAN
   (`gfpgan-1024.onnx`, on a 512 px aligned face) restores the detail that a
   128 px swap loses on a big photo. It runs on the **swapped faces only**;
   every other pixel stays exactly as in the original. If enhancement fails,
   the plain swap is kept and the error is logged.

GFPGAN runs through CoreML (compute units `ALL`) and takes about 1.5 GB of
memory. It is loaded on the first swap (and downloaded then if missing:
about 370 MB, plus a CoreML-optimised copy next to it), kept for the next
photos, and released when you switch back to **Live** unless a job is still
running.

After the swap the stage shows the result with a
*Swapped · hold Space to compare* chip. Holding the compare button or `Space`
shows the original (the chip says *Original*).

## Loading and saving photos

`photo_io.py` handles the files.

**Loading** (`load_image()`):

- Pillow decodes the file and the EXIF orientation is applied, so faces are
  found on the upright picture you see in Finder.
- HEIC/HEIF, which Pillow can't decode here, is converted first with
  macOS's own `/usr/bin/sips` to a best-quality temporary JPEG (EXIF and ICC
  kept).
- CMYK is converted to sRGB through its ICC profile, 16-bit and float
  greyscale are reduced to 8 bits, and transparency is flattened onto white.

**Saving** (`save_image()`, `⌘S` or **Save**):

- **Name:** `<name>-mirage.<ext>` next to the original; if that exists,
  `-mirage-2`, `-mirage-3`, and so on. Saving a result again gives
  `photo-mirage-2.jpg`, not `photo-mirage-mirage.jpg`. The extension keeps
  its letter case (`IMG_1234.JPG` → `IMG_1234-mirage.JPG`).
- **Format:** JPEG stays JPEG (quality 95, no chroma subsampling), HEIC/HEIF
  becomes JPEG, PNG stays PNG, WebP stays WebP (quality 95), TIFF stays TIFF
  (LZW, or uncompressed when it carries EXIF, which libtiff can't write), BMP
  stays BMP (no metadata). Anything else Pillow can read is saved as PNG.
- **Metadata:** EXIF is kept (camera, date, GPS…), with *Orientation* reset
  to 1 because the pixels are saved upright, and the pixel dimensions set to
  the saved size. The embedded thumbnail is removed, because it would still
  show the original face. If Pillow can't rewrite a camera's EXIF, the raw
  bytes are patched in place instead. EXIF over 64 KB is dropped for JPEG,
  which can't hold more. The ICC colour profile and the DPI are kept.
- **Atomic, never overwriting:** the image is written to a hidden temporary
  file in the same folder and flushed to disk, then hard-linked to the free
  name, which fails instead of replacing a file that appeared in the meantime.
  On volumes without hard links (exFAT, some network shares) it is renamed
  instead. The original is never opened for writing.

After saving, the button turns into **Show in Finder**.

## Batch

Several photos or a folder open as a list under the header *N photos*, with
a subtitle that says who everyone becomes (*The main face in each becomes
Anna*, or *Pick a face on the right first* while *Me* is selected). Each row
has a centre-cropped thumbnail (for the first 300 files), the file name and a
status pill. The button reads **Swap in N photos**, or *Pick a face on the
right* until a face is selected.

`batch.run_batch()` then processes the files in order on one worker thread:
load → find faces → automatic plan (*This is me* first, then the main face,
with the face that was selected when you pressed the button) → render → save
next to the original. *Enhance faces* applies as for single photos.

| Status | Meaning |
|---|---|
| Waiting | not reached yet |
| Swapping… | being processed now |
| Saved | the result is next to the original |
| No face | no face was found |
| Skipped | faces were found but the plan swaps nobody |
| Failed | an error; it is logged and the batch goes on |

While it runs, the subtitle counts (*Swapping faces… 2 of 3*), a progress
bar fills, count pills in the header add up *Saved*, *No face* (with
*Skipped*) and *Failed*, and the list keeps the photo being worked on in
view. When a photo fails, the error is shown under its name.

**Cancel** is checked between files: the current photo finishes (and is
saved), the rest stay *Waiting*. The subtitle then says *Stopped · N left*,
the button offers **Continue · N left**, and the folder button shows what
was saved so far. A finished batch says *Done · saved next to the
originals*, and the button turns into **Show in Finder**, which selects the
first result. The list already shows the result, so there is no toast
unless something failed or the window isn't showing the list (you switched
to Live, say): *Saved 12 of 13 · 1 without a face*. The Mac is kept awake
while a batch runs.

## Videos

Videos need `ffmpeg` and `ffprobe`. Mirage looks for them on `PATH`, then in
`/opt/homebrew/bin` and `/usr/local/bin` (an app started from Finder has no
Homebrew `PATH`). `make install` installs ffmpeg with Homebrew; without it,
opening a video shows *Videos need ffmpeg: run “brew install ffmpeg” in
Terminal.*

### Probing

`video.probe()` asks `ffprobe` for the upright size, frame rate, frame count,
length, rotation, codec, bit rate, pixel format, colour matrix, HDR transfer
(HLG or PQ), pixel aspect ratio and the first audio track. Results are cached
per file (path, modification time and size). Still images and files without
a video stream are refused with a message.

### The pipeline

```
FrameReader ─► detect + track ─► swap ──────────► FrameWriter
(ffmpeg,        (GPU, thread;     (Neural Engine,   (ffmpeg, thread)
 thread)         re-id at times)   render thread)
```

- **Reader** (`mirage-video-read`): ffmpeg decodes to raw BGR frames on a
  pipe. VideoToolbox decodes H.264, HEVC, ProRes, VP9, AV1, MPEG-1/2/4 and
  H.263 in hardware; if a decoder gives no frames, the reader falls back from
  the HDR path to plain VideoToolbox to software.
- **Detect + track** (`mirage-video-detect`): a 640 px SCRFD detector of its
  own on the **GPU** (CoreML `CPUAndGPU`, constant-folded for the fixed input
  size; CPU if that fails) finds the faces in every frame. It is separate from
  Live's 320 px detector, so a render and a live session can run at the same
  time. The identity tracker (below) runs here too, including the occasional
  recognition, so the next stage does nothing but swap.
- **Swap** (the render's own worker thread): inswapper on the **Neural
  Engine** for every face that was matched to a chosen person, with the same
  *Look* settings as photos (*Sharpness* is applied per face, without Live's
  frame-to-frame blending). With **Enhance faces** on (for a video its
  tooltip reads *Enhance faces (slower)*; `Settings.video_enhance`, off by
  default), GPEN-BFR-256 then restores each swapped face. The swap is the
  slowest step and sets the pace.
- **Writer** (`mirage-video-write`): ffmpeg encodes.

Between stages sit queues of 2 to 4 frames (fewer for big frames, about
64 MB per queue), so memory stays flat however long the video is.

### Following people

The people to swap come from the plan on the sample frame: for every face
given a library face, Mirage keeps that person's embedding and the library
face's embedding. In every frame the `IdentityTracker` decides who is who:

- Detections are matched to the previous frame's faces by box overlap
  (IoU ≥ 0.3, best overlaps first). A face that goes undetected keeps its
  track for up to 5 frames.
- Recognition does not run on every face in every frame. It runs for a new
  face, again every **12 frames** per face, and at once whenever faces
  overlap, because two people crossing could otherwise swap tracks.
- A face is person *k* when its cosine similarity to *k* is the best and at
  least **0.40**. A face already known as *k* keeps it down to 0.30 (75 % of
  the threshold), so a turned head doesn't make the swap flicker. Each person
  goes to at most one face per frame.
- Faces that match nobody are left as is. Boxes and landmarks are smoothed
  per face, as in Live.

### Output

- **Name:** `<name>-mirage.mp4` next to the original (`-mirage-2.mp4`, … if
  taken). Rendering onto the original itself is refused.
- **Video:** H.264 High profile, 4:2:0, tagged BT.709 SDR, with the index at
  the front of the file (`+faststart`) so it starts playing at once.
- **Encoder:** `h264_videotoolbox`, the Mac's hardware encoder, when a 0.1 s
  dry run at that size works (successes are cached); otherwise `libx264`
  (CRF 18, preset medium).
- **Bit rate** (VideoToolbox): the source's video bit rate × 1.1, and × 1.5
  more for HEVC, VP9 and AV1 sources (H.264 needs more bits for the same
  quality), kept between 2 and 40 Mbit/s. If the source's bit rate is
  unknown, constant quality (`-q:v 65`) is used instead. A keyframe every 2 s.
- **Frame rate:** the output has the same, constant rate. Phone videos are
  variable-rate around a nominal rate (say, an average of 29.98 for 30 fps);
  when the nominal and average rates are within 1 % of each other the nominal
  one is used, otherwise the average. Decoding at that rate drops or repeats
  the odd frame, and encoding at exactly that rate keeps the sound in sync.
- **Rotation:** frames are decoded upright (ffmpeg's autorotate, or a GPU
  transpose on the HDR path), so the result needs no rotation flag.
- **HDR:** iPhone videos are HLG by default; HLG and PQ are tone-mapped to SDR
  BT.709 by VideoToolbox on the GPU (`scale_vt`). If that path can't be used,
  decoding falls back to plain VideoToolbox or software, and the result looks
  washed out.
- **Odd sizes** are padded by one pixel to even (4:2:0 needs it); non-square
  pixels keep their aspect ratio. The colour matrix is read from the file
  (BT.709, BT.601 or BT.2020; untagged video is taken as BT.709 for HD and
  BT.601 for SD).
- **Sound:** a final remux adds the original's first audio track: copied as
  is when it is AAC, ALAC or MP3, otherwise re-encoded to AAC at 192 kbit/s.
  If even that fails, the video is saved without sound and the log says why.
  The original's file-level metadata (such as the creation date) is copied.
- **Atomic:** everything is written to hidden temporary files in the same
  folder, and the result appears under its final name only when complete.
  **Cancel** or any error kills ffmpeg and deletes those files, so a partial
  video is never left behind.

While it runs, the frame dims and the capsule on it says *Making the
video…*, with a progress bar and *Frame 120 of 900 · 13 fps · 1:00 left*
under it, updated about four times a second; the speed is measured over the
last 3 seconds, and the time left is the remaining frames divided by that
speed. The big button is a red **Cancel** meanwhile. When the video is done,
a toast says *Video saved next to the original: “name-mirage.mp4”*, the big
button turns into **Play video** (it opens in your default player) and a
folder button next to it shows the file in Finder. The Mac is kept awake
while a video renders.

## Speed on a MacBook Air M1

Measured end to end in the app on a MacBook Air M1 with 8 GB of memory.

| Job | Time |
|---|---|
| Finding faces in a 2400×1500 group photo with 3 faces | about 0.1–0.4 s (the very first time about 10 s, while the models load) |
| Swap + GFPGAN, per swapped face | about 0.4–0.5 s (the first swap about 4–7 s, while GFPGAN loads) |
| Saving a 12 MP JPEG | about 0.1 s |
| Video, 1280×720 at 30 fps, one face | about 13–14 fps |
| Video, two people crossing | about 10 fps |
| Video, 640×480, 5 s | about 12 s in total |

In videos the swap on the Neural Engine, about 65 ms per face, is the
bottleneck; decoding, detection and encoding run alongside it.

## Running well on M-series Macs

| Concern | What Mirage does |
|---|---|
| Neural Engine | The swap runs there (CoreML `CPUAndNeuralEngine`, about 63–65 ms per face on an M1). Detection is kept off it; for GFPGAN, CoreML picks the units itself (`ALL`). |
| GPU | Video face detection (640 px, CoreML `CPUAndGPU`) runs in its own thread in parallel with the swap; HDR tone-mapping and rotation of HDR frames also happen on the GPU. |
| CPU | Photo detection and gender/age estimates: one-off jobs that don't compete with Live. |
| Media engine | VideoToolbox decodes and encodes; the CPU encoder (`libx264`) is only a fallback. |
| Memory (8 GB) | GFPGAN (about 1.5 GB with CoreML) loads on the first photo swap and is released when you leave the mode. Video frames in flight are capped (2–4 per queue, about 64 MB). Video enhancement is off unless you turn it on. |
| Live + a render | Both can run at once: they use separate detectors (Live 320 px on the GPU, video 640 px on the GPU, photos on the CPU), but they share the Neural Engine, so the call gets fewer fps while a render runs. Mirage says so once (*You're live: the call will get fewer fps while this runs.*). Stop Live for the fastest render. |
| Heat and sleep | A fanless Air slows down in long renders; the time left is measured, not guessed, so it adjusts. The Mac is kept awake (an `NSProcessInfo` activity) during batches and video renders. |

## Code map

| Module | Role |
|---|---|
| `mirage/media/types.py` | plain data: `TargetFace`, `SourceInfo`, `Plan`, `RenderOptions`, `VideoInfo`, `VideoIdentity`, `VideoProgress` |
| `mirage/media/analyze.py` | photo → `list[TargetFace]`: CPU detection at 640 (+1280), NMS, embeddings, gender/age, numbering |
| `mirage/media/plan.py` | pure logic: automatic plan, main face, *find me*, suggestions, cosine similarity |
| `mirage/media/render.py` | `PhotoRenderer`: full-resolution swap and GFPGAN on the swapped faces; `release()` |
| `mirage/media/photo_io.py` | collecting dropped files, loading upright (HEIC via `sips`), saving next to the original with metadata |
| `mirage/media/batch.py` | `run_batch()`: the automatic plan over many photos, with statuses and cancel |
| `mirage/media/video.py` | ffmpeg lookup, probing, sample frames, `FrameReader` / `FrameWriter`, `IdentityTracker`, `render_video()` |
| `mirage/ui/media_page.py` | `MediaPage`: the mode's state, worker threads, the control bar and its one primary button |
| `mirage/ui/media_view.py` | `MediaView`: the stage (picture, lettered faces with outlines or corner marks, chips, busy capsule, batch list) |
| `mirage/ui/main_window.py` | the mode switch, drops, shortcuts, *This is me* in the face menu |

Tests: `tests/mirage/test_media_plan.py`, `test_media_batch.py` (with
fakes), `test_photo_io.py` and `test_video.py` (the ffmpeg-based tests are
skipped when ffmpeg is not installed).
