# Deep-Live-Cam (the engine inside Mirage)

This folder is [Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam), the
open-source real-time face swap by [hacksider](https://github.com/hacksider)
(Kenneth Estanislao) and
[its contributors](https://github.com/hacksider/Deep-Live-Cam/graphs/contributors),
itself based on [roop](https://github.com/s0md3v/roop). Mirage uses it as its
face-swap engine: face detection and analysis (through InsightFace), the swap
model, the face enhancers and the model downloads. Everything you see and
click in Mirage lives in [`mirage/`](../../mirage) instead.

| | |
|---|---|
| Upstream | <https://github.com/hacksider/Deep-Live-Cam> |
| Based on | commit [`759e3f9`](https://github.com/hacksider/Deep-Live-Cam/commit/759e3f985811985cf6c00a3e43e9579652c318f5) (26 September 2026), also recorded in [`UPSTREAM_COMMIT`](UPSTREAM_COMMIT) |
| License | [GNU AGPL-3.0](LICENSE) (a copy of the repository's [LICENSE](../../LICENSE)), the same as Mirage. The copyright notices in the code are kept as they were. |

## What is here

| Path | What it is |
|---|---|
| `modules/` | The engine. Its code imports itself as the top-level package `modules`, so [`mirage/__init__.py`](../../mirage/__init__.py) puts this folder on Python's path. |
| `run.py`, `tkinter_fix.py`, `locales/` | The classic Deep-Live-Cam window and its translations: `make classic`. |
| `tests/`, `benchmark_pipeline.py`, `mypi.ini` | Upstream's tests, pipeline benchmark and mypy settings, kept as they were. |
| `models` | A link to the repository's `models/` folder, where Mirage keeps the downloaded models, so the engine finds them too. |

Upstream's README, demo media and Windows launchers are not copied; see
the upstream repository for those.

## What Mirage changed

Mirage keeps its changes to the engine small and lists them here (section 5(a)
of the AGPL; see also [NOTICE.md](../../NOTICE.md)):

| File | Change |
|---|---|
| `modules/virtualcam_out.py` | **New.** Sends frames straight to OBS Virtual Camera at a fixed 1280×720, so Zoom never sees the stream restart. Used by both Mirage and the classic window. |
| `modules/processors/frame/face_swapper.py` | The swap model runs on the Apple Neural Engine (`CPUAndNeuralEngine`: about 63 ms per frame on an M1 instead of 82 ms); a failed model load is remembered instead of retried on every frame; a failed CoreML rewrite falls back to the original model. |
| `modules/onnx_optimize.py` | The CoreML-optimised model is written to a temporary file and then renamed, so an interrupted write never leaves a broken model behind. |
| `modules/face_analyser.py` | The largest face wins in live mode (the person at the camera, not a poster behind them); `load_source_face()` rejects unreadable files and retries close-up portraits with a border around them. |
| `modules/video_capture.py` | A camera that opens but sends no frames fails within seconds instead of hanging; slow-starting cameras get time to warm up. |
| `modules/model_downloader.py`, `modules/utilities.py` | Model downloads verify TLS certificates (with certifi's CA bundle) instead of turning verification off on macOS. |
| `modules/core.py` | Quitting stops the live threads first and ends the Qt event loop normally, with no `SystemExit` inside a Qt slot. |
| `modules/ui.py` | Fixes in the classic window: a bad frame or a short camera gap no longer ends live mode, no deadlock on a second Live click, the models load in the background, the macOS camera list (built-in camera first, OBS Virtual Camera hidden), and a working random face download. |
| `locales/ru.json` | Russian translation of the classic window rewritten and completed. |

`git log -- third_party/deep-live-cam` shows each change in detail. The
repository's first commit is this engine exactly as upstream published it at
`759e3f9`.

## Updating from upstream

```bash
scripts/update_engine.sh            # the latest Deep-Live-Cam main
scripts/update_engine.sh <commit>   # or a specific upstream commit
```

The script takes upstream's changes since `UPSTREAM_COMMIT`, applies them on
top of Mirage's with a three-way merge, and records the new commit. Resolve
any conflicts, compare upstream's `requirements.txt` with ours, run
`make test`, try both `make run` and `make classic`, then commit.
