# Notice

## This is a modified version of Deep-Live-Cam

Mirage is a **modified version of
[Deep-Live-Cam](https://github.com/hacksider/Deep-Live-Cam)** by hacksider and
contributors. It was forked from Deep-Live-Cam `main` (commit `759e3f9`) and
modified by the Mirage contributors ([RebSem](https://github.com/RebSem)) in
**September 2026**.

This notice is given under section 5(a) of the GNU Affero General Public
License v3.0. Like the original, Mirage is released under the
[AGPL-3.0](LICENSE); the `LICENSE` file is unchanged from upstream. The complete
source code of Mirage is available at <https://github.com/RebSem/mirage>.

### Summary of changes

- **New:** the `mirage/` package, a macOS-first app with a native Liquid Glass
  window, a face library with cached embeddings, quality presets, output to
  OBS Virtual Camera at a fixed 1280×720, keep-awake while live, a
  single-instance guard, clean start and quit, English and Russian UI.
- **New:** `scripts/` (installer, `Mirage.app` bundle, icon, benchmark),
  `tests/mirage/`, a `Makefile`, and the documentation in `docs/`,
  `README.md`, `README.ru.md`, `CHANGELOG.md`, `CONTRIBUTING.md` and this file.
- **Changed:** small, targeted fixes in the upstream engine under `modules/`:
  live-mode stability, clean shutdown, camera selection on macOS, face
  detection for close-up photos, background model loading, and running the
  swap model on the Apple Neural Engine. [CHANGELOG.md](CHANGELOG.md) lists
  them; `git log` has the details.
- **Security:** model downloads verify TLS certificates, using certifi's CA
  bundle (`modules/model_downloader.py`, `modules/utilities.py`). Upstream
  turned certificate checks off on macOS, so a model file could have been
  swapped on the way without anyone noticing.
- **Moved:** the upstream README now lives in
  [docs/upstream/README.md](docs/upstream/README.md).

The upstream copyright and license notices in the code are kept as they were.

## Models: personal, non-commercial use only

Mirage downloads pretrained models that are **not** covered by the AGPL and are
not stored in this repository. The most important one: InsightFace states that
its pretrained models are available for **non-commercial research purposes
only**. The face swap in Mirage cannot work without them.

So, plainly: **Mirage as a whole is for personal, non-commercial fun.** Do not
use it in a product, a paid service, for advertising, or to make money in any
other way. If you need that, talk to the model authors first.

## Third-party components

| Component | Used for | License | How it gets on your Mac |
|---|---|---|---|
| [InsightFace](https://github.com/deepinsight/insightface) library | face detection and analysis | MIT (code) | pip, from PyPI |
| InsightFace `buffalo_l` models | detecting and recognising faces | non-commercial research use only | downloaded to `~/.insightface/models` |
| InsightFace `inswapper_128` model (fp16 or fp32 file) | the face swap itself | non-commercial research use only | downloaded to `models/` |
| [GPEN](https://github.com/yangxy/GPEN) `GPEN-BFR-256.onnx` (ONNX export from [harisreedhar/Face-Upscalers-ONNX](https://github.com/harisreedhar/Face-Upscalers-ONNX)) | face enhancement (*Best* preset) | no clear license published; treat as non-commercial (see note below) | downloaded to `models/` (about 75 MB) the first time you choose *Best*, or ahead of time with `scripts/install.sh --with-enhancer` |
| [GFPGAN](https://github.com/TencentARC/GFPGAN) (`gfpgan-1024.onnx`) | face enhancement, used by the classic UI only | code: Apache-2.0; see note below for the model | downloaded to `models/` only if you turn it on in the classic UI |
| Generated faces from [thispersondoesnotexist.com](https://thispersondoesnotexist.com) | the optional 🎲 *Random* face | images generated with StyleGAN; the site states no terms, so treat them as personal use only | downloaded on demand, one image each time you press *Random*, straight to your Mac (it is kept in your face library) |
| [OBS Studio](https://github.com/obsproject/obs-studio) | the *OBS Virtual Camera* device | GPL-2.0-or-later | separate app you install yourself (the installer can offer it); **not bundled** |
| [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) | sending frames to OBS Virtual Camera | GPL-2.0 | optional runtime dependency, pip from PyPI into your local venv; **not bundled** |
| [PySide6 / Qt for Python](https://pypi.org/project/PySide6/) | the user interface | LGPL-3.0 (also offered as GPL-2.0 / GPL-3.0 / commercial) | pip, from PyPI |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | running the models (CoreML, Neural Engine) | MIT | pip, from PyPI |
| [OpenCV](https://github.com/opencv/opencv) via [opencv-python](https://github.com/opencv/opencv-python) | camera capture and image processing | Apache-2.0 (OpenCV); the wheels bundle FFmpeg under LGPL-2.1 | pip, from PyPI |

Other Python dependencies are listed in [requirements.txt](requirements.txt);
each keeps its own license.

Notes:

- **Models are downloaded from** the Deep-Live-Cam Hugging Face repository
  [`hacksider/deep-live-cam`](https://huggingface.co/hacksider/deep-live-cam).
  That repository is tagged GPL-3.0, but the InsightFace terms above still
  apply to the InsightFace models it redistributes.
- **GPEN:** Mirage's *Best* preset uses `GPEN-BFR-256`; the classic UI also
  offers `GPEN-BFR-512`, downloaded only when selected there. The GPEN
  repository ([yangxy/GPEN](https://github.com/yangxy/GPEN)) does not publish a
  clear license for the models, and the ONNX export Mirage uses comes from
  [harisreedhar/Face-Upscalers-ONNX](https://github.com/harisreedhar/Face-Upscalers-ONNX).
  Treat them as non-commercial. The file is fetched from the Deep-Live-Cam
  Hugging Face repository, with the Face-Upscalers-ONNX release as a fallback.
- **GFPGAN** is used only by the classic Deep-Live-Cam UI. The code is
  Apache-2.0, but its license file also lists parts under more restrictive
  terms: StyleGAN2 (NVIDIA Source Code License, non-commercial) and DFDNet
  (CC BY-NC-SA 4.0). No separate license is stated for the released weights.
  Treat the enhancer model as non-commercial too.
- **Random faces** come from [thispersondoesnotexist.com](https://thispersondoesnotexist.com),
  which shows faces generated by a StyleGAN model rather than photos of real
  people. Mirage downloads one only when you press *Random*, and nothing is
  sent to the site apart from that request. The site does not state terms of
  use, so keep these faces to personal use.
- **pyvirtualcam** is published as GPL-2.0 (the PyPI classifier says GPLv2,
  without "or later"). Mirage does not include or redistribute it: you install
  it from PyPI into your own virtual environment, and Mirage imports it only
  to talk to the virtual camera. If you ever distribute a self-contained build
  that bundles pyvirtualcam together with this AGPL code, check license
  compatibility first.
- **OBS Studio** runs as its own application. Mirage never ships or links OBS
  code; it only writes frames to the virtual camera that OBS installs.

## Trademarks

Apple, macOS, Liquid Glass and Apple Neural Engine are trademarks of Apple
Inc. Zoom, Google Meet, OBS and the other names mentioned here belong to their
owners. Mirage is not affiliated with or endorsed by any of them, nor by the
Deep-Live-Cam team.

## Sources

Checked in September 2026. This is a good-faith summary, not legal advice.

- Deep-Live-Cam, AGPL-3.0: <https://github.com/hacksider/Deep-Live-Cam>
- AGPL-3.0 text, section 5(a): <https://www.gnu.org/licenses/agpl-3.0.html>
- InsightFace license (code MIT, models non-commercial research only):
  <https://github.com/deepinsight/insightface#license> and
  <https://github.com/deepinsight/insightface/tree/master/python-package>
- GFPGAN license: <https://github.com/TencentARC/GFPGAN/blob/master/LICENSE>
- OBS Studio, GPL-2.0-or-later: <https://github.com/obsproject/obs-studio>
- pyvirtualcam, GPL-2.0: <https://github.com/letmaik/pyvirtualcam> and
  <https://pypi.org/project/pyvirtualcam/>
- PySide6, LGPL-3.0 / GPL-2.0 / GPL-3.0: <https://pypi.org/project/PySide6/>
- ONNX Runtime, MIT: <https://github.com/microsoft/onnxruntime>
- OpenCV, Apache-2.0: <https://github.com/opencv/opencv>; opencv-python wheels
  (MIT, bundled FFmpeg LGPL-2.1): <https://github.com/opencv/opencv-python>
- Model hosting: <https://huggingface.co/hacksider/deep-live-cam>
- GPEN: <https://github.com/yangxy/GPEN>; ONNX export:
  <https://github.com/harisreedhar/Face-Upscalers-ONNX>
- Random faces: <https://thispersondoesnotexist.com>
