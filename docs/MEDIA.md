# Photos & videos mode

Swap faces in files you already have: a single photo, a whole batch, or a
video. Mirage finds the faces, proposes who should become whom, lets you
correct it with a click, renders at full resolution and saves next to the
original.

## How Mirage decides what to swap

For every photo (and for a video's sample frames) Mirage detects all faces and
computes, for each one, an identity embedding plus gender and age. Then it
builds a *plan*: target face → library face, or "leave as is".

The automatic plan follows these rules, in order:

1. **Find me.** If one of your library faces is marked *This is me*, and a
   face in the photo matches it (cosine similarity ≥ 0.40), that face is the
   one to swap.
2. **Main face.** Otherwise the main face is swapped: the largest face,
   and on near-ties (within 15 % area) the one closest to the centre.
3. Everyone else is left alone.

The face it gets is the one selected in the gallery. With nothing selected
(*Me*), the plan is empty and Mirage asks you to pick a face.

Click any face in the photo to change its assignment. The picker lists
*Leave as is*, then the library sorted by **how natural the swap will look**:
same gender first, then closest age. The top suggestions are marked. *Swap
everyone* assigns the selected face to every face in one go.

## Photos

- Open with ⌘O, drag files onto the window, or use *File → Open Photos*.
- Faces get numbered outlines (left → right). Assigned ones show the
  source's avatar.
- **Swap** renders at the photo's full resolution: InsightFace inswapper on
  the Neural Engine, then GFPGAN on the swapped faces only (photos only; about
  0.4 s per face on an M1), then the usual paste-back with the Look settings
  (blend, keep my mouth, smooth edges, sharpness).
- **Hold to compare** (or hold `Space`) shows the original.
- **Save** writes `<name>-mirage.<ext>` next to the original (never
  overwrites: `-mirage-2`, `-mirage-3`, …). The original file is untouched.
  EXIF is kept, the orientation tag is reset because pixels are saved upright.
  HEIC is saved as JPEG.

### Batch

Drop several photos or a folder. Each file gets the automatic plan, is
rendered and saved next to its original. A list shows each file's status
(*waiting*, *swapping*, *saved*, *no face*, *failed*). Cancel stops after the
current file. Files where the plan is empty are skipped, not failed.

## Videos

- Open a video (`.mp4`, `.mov`, `.m4v`, `.mkv`, `.avi`, `.webm`). Mirage
  samples a few frames, shows the one with the biggest face, detects the
  people in it and proposes the plan with the same rules as photos.
- Each assignment is **by identity**, not by position: during rendering every
  detected face is matched to the chosen people by embedding, so the right
  person gets the right face even when they move or the shot changes.
- **Render** runs decode → detect → swap → encode in a pipeline and shows
  progress, speed and time left. Cancel removes the partial file.
- Output: `<name>-mirage.mp4` next to the original, H.264 via the Mac's
  hardware encoder (`h264_videotoolbox`), original audio copied, same frame
  rate and size.

## Running well on Apple M-series Macs

| Concern | What Mirage does |
|---|---|
| Neural Engine | The swap model runs with CoreML `CPUAndNeuralEngine` (~63 ms/face on M1). |
| GPU in parallel | Video face detection runs on the GPU (CoreML `CPUAndGPU`, 640 px) in its own thread while the swap uses the Neural Engine. |
| CPU for one-offs | Photo detection uses a CPU 640 px detector (~100 ms even on a 3000×2000 group photo), plus a 1280 px pass when faces are tiny. |
| Hardware video | Encoding uses VideoToolbox (the media engine), decoding uses ffmpeg with VideoToolbox acceleration when available. |
| Memory (8 GB) | GFPGAN (~1.5 GB with CoreML) loads only when a photo is swapped and is released when you leave the mode; video enhancement is opt-in. |
| Heat | A fanless Air slows down under long renders; the ETA is measured, not guessed, and the Mac is kept awake while a render runs. |
| Live + render | Both can run, but they share the Neural Engine: live fps drops while a render is going. |
| Identity tracking | Recognition is not run on every face every frame: faces are followed by overlap (IoU) and re-identified every 12 frames or when a new face appears. |

## Code map

| module | role |
|---|---|
| `mirage/media/types.py` | `TargetFace`, `SourceInfo`, `Plan`, `RenderOptions`, `VideoInfo`, `VideoIdentity`, `VideoProgress` |
| `mirage/media/analyze.py` | photo → `list[TargetFace]` (detection 640/1280 on CPU, embeddings, gender/age) |
| `mirage/media/plan.py` | pure logic: automatic plan, suggestions, main face, cosine similarity |
| `mirage/media/photo_io.py` | load (EXIF orientation, HEIC via `sips`), save next to the original with EXIF |
| `mirage/media/render.py` | photo render: swap + GFPGAN on assigned faces |
| `mirage/media/video.py` | probe, frame reader/writer (ffmpeg), identity tracker, video render job |
| `mirage/media/batch.py` | batch job over many photos |
| `mirage/ui/media_view.py` | the Photos & videos stage |
