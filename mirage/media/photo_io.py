"""Photo files: find them, load them upright, save the result next to the original.

Loading applies the EXIF orientation, so callers always get upright BGR pixels
(what the user sees in Finder). HEIC/HEIF has no Pillow decoder here, so it is
converted with macOS's built-in /usr/bin/sips first.

Saving writes `<name>-mirage.<ext>` beside the original (`-mirage-2`, `-mirage-3`,
... if taken), never replaces an existing file, and keeps EXIF (Orientation reset
to 1, embedded thumbnail of the original dropped), the ICC profile and the DPI.
HEIC is saved as JPEG.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import logging
import os
import re
import secrets
import stat
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)

IMAGE_EXTS: tuple[str, ...] = ("jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "heic", "heif")
VIDEO_EXTS: tuple[str, ...] = ("mp4", "mov", "m4v", "mkv", "avi", "webm")

JPEG_QUALITY = 95
WEBP_QUALITY = 95
SIPS = "/usr/bin/sips"
SIPS_TIMEOUT = 120.0  # seconds; a 48 MP HEIC converts in well under a second on M1

_OUTPUT_STEM = re.compile(r"-mirage(?:-\d+)?$", re.IGNORECASE)
_DIGITS = re.compile(r"(\d+)", re.ASCII)
_EXIF_HEADER = b"Exif\x00\x00"
_JPEG_MAX_EXIF = 65533  # an APP1 segment holds at most this much
_HEIF_BRANDS = {
    b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1",
}

# Pillow's format name -> PhotoMeta.format. Anything else is saved as PNG (lossless).
_FORMATS = {
    "JPEG": "jpeg", "MPO": "jpeg", "PNG": "png", "WEBP": "webp", "TIFF": "tiff",
    "BMP": "bmp", "DIB": "bmp", "HEIF": "heic", "AVIF": "jpeg",
}
# PhotoMeta.format -> accepted output extensions, the first is the default.
_FORMAT_EXTS = {
    "jpeg": ("jpg", "jpeg"), "heic": ("jpg", "jpeg"), "png": ("png",),
    "webp": ("webp",), "tiff": ("tif", "tiff"), "bmp": ("bmp",),
}

# EXIF tags
_ORIENTATION = 0x0112
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_EXIF_WIDTH, _EXIF_HEIGHT = 0xA002, 0xA003
# IFD0 tags worth carrying over from a TIFF, whose own IFD0 also holds strip layout etc.
_DESCRIPTIVE_TAGS = (0x010E, 0x010F, 0x0110, 0x0112, 0x0131, 0x0132, 0x013B, 0x8298)

_DECODE_ERRORS = (OSError, SyntaxError, ValueError, EOFError, struct.error, zlib.error)


@dataclass
class PhotoMeta:
    """What a saved result keeps from its source file.

    `exif` is the source's EXIF as read (with the "Exif\\0\\0" header); its
    Orientation still describes the file on disk, save_image resets it.
    """

    format: str                                  # jpeg | png | webp | tiff | bmp | heic
    exif: bytes | None = None
    icc_profile: bytes | None = None
    dpi: tuple[float, float] | None = None


# --- finding files ------------------------------------------------------------


def _ext(path: str | os.PathLike[str]) -> str:
    return Path(path).suffix[1:].lower()


def is_image(path: str | os.PathLike[str]) -> bool:
    return _ext(path) in IMAGE_EXTS


def is_video(path: str | os.PathLike[str]) -> bool:
    return _ext(path) in VIDEO_EXTS


def _natural_key(text: str) -> tuple[Any, ...]:
    """"img2" before "img10", case-insensitive."""
    parts = _DIGITS.split(text.casefold())
    return tuple(int(part) if i % 2 else part for i, part in enumerate(parts))


def _name_order(path: Path) -> tuple[Any, ...]:
    return _natural_key(path.name), _natural_key(str(path.parent))


def _is_hidden(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith("."):  # also AppleDouble "._name" files on non-Mac volumes
        return True
    with contextlib.suppress(OSError):
        return bool(getattr(entry.stat(), "st_flags", 0) & stat.UF_HIDDEN)
    return False


def _folder_files(folder: Path) -> list[Path]:
    """Direct children that are files, without hidden ones and earlier Mirage results."""
    try:
        with os.scandir(folder) as entries:
            return [
                folder / entry.name
                for entry in entries
                if entry.is_file()
                and not _is_hidden(entry)
                and not _OUTPUT_STEM.search(Path(entry.name).stem)
            ]
    except OSError as exc:
        log.warning("cannot list %s: %s", folder, exc)
        return []


def collect_media(paths: Iterable[Path]) -> tuple[list[Path], list[Path]]:
    """Split dropped files and folders into (images, videos).

    Folders contribute their direct children only. Files named explicitly are
    taken as they are (even hidden or `-mirage` ones). Duplicates are dropped
    and both lists are sorted naturally by file name.
    """
    seen: set[object] = set()
    images: list[Path] = []
    videos: list[Path] = []
    for raw in paths:
        path = Path(os.path.abspath(raw))
        candidates = _folder_files(path) if path.is_dir() else [path] if path.is_file() else []
        for file in candidates:
            if is_image(file):
                bucket = images
            elif is_video(file):
                bucket = videos
            else:
                continue
            try:
                st = file.stat()
            except OSError:
                continue
            # Same file via another path, letter case or link; some network volumes report no inodes.
            key: object = (st.st_dev, st.st_ino) if st.st_ino else str(file)
            if key in seen:
                continue
            seen.add(key)
            bucket.append(file)
    return sorted(images, key=_name_order), sorted(videos, key=_name_order)


# --- loading ------------------------------------------------------------------


def load_image(path: str | os.PathLike[str]) -> tuple[np.ndarray, PhotoMeta]:
    """Read a photo as upright BGR uint8 plus the metadata save_image keeps.

    Raises ValueError("not an image") for missing, unreadable or undecodable files.
    """
    path = Path(path)
    try:
        with Image.open(path) as img:
            return _from_pillow(img, None)
    except Image.DecompressionBombError as exc:
        raise ValueError("image too large") from exc
    except UnidentifiedImageError as exc:
        if not _looks_like_heif(path):
            raise ValueError("not an image") from exc
    except _DECODE_ERRORS as exc:
        raise ValueError("not an image") from exc
    return _load_with_sips(path)


def _looks_like_heif(path: Path) -> bool:
    if _ext(path) in ("heic", "heif"):
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    return head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS


def _load_with_sips(path: Path) -> tuple[np.ndarray, PhotoMeta]:
    """HEIC/HEIF: sips converts to a near-lossless temp JPEG, keeping EXIF and ICC.

    sips leaves the pixels as stored and keeps the Orientation tag, so the usual
    EXIF transpose makes them upright.
    """
    if sys.platform != "darwin" or not os.access(SIPS, os.X_OK):
        raise ValueError("not an image")
    with tempfile.TemporaryDirectory(prefix="mirage-heic-") as tmp:
        out = Path(tmp) / "converted.jpg"
        cmd = [SIPS, "-s", "format", "jpeg", "-s", "formatOptions", "best",
               str(path.absolute()), "--out", str(out)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=SIPS_TIMEOUT)
            with Image.open(out) as img:
                return _from_pillow(img, "heic")
        except Image.DecompressionBombError as exc:
            raise ValueError("image too large") from exc
        except (subprocess.SubprocessError, *_DECODE_ERRORS) as exc:
            raise ValueError("not an image") from exc


def _from_pillow(img: Image.Image, fmt: str | None) -> tuple[np.ndarray, PhotoMeta]:
    img.load()
    fmt = fmt or _FORMATS.get(img.format or "", "png")
    icc = img.info.get("icc_profile") or None
    dpi = _dpi(img.info.get("dpi"))
    exif = _source_exif(img)
    orientation = 1
    try:
        orientation = int(img.getexif().get(_ORIENTATION, 1))
        ImageOps.exif_transpose(img, in_place=True)
    except Exception as exc:  # broken EXIF must not make the photo unreadable
        log.warning("ignoring bad EXIF orientation: %s", exc)
    if orientation in (5, 6, 7, 8) and dpi is not None:  # quarter turn: axes swap
        dpi = (dpi[1], dpi[0])
    rgb, icc = _to_rgb(img, icc)
    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    return bgr, PhotoMeta(format=fmt, exif=exif, icc_profile=icc, dpi=dpi)


def _dpi(value: object) -> tuple[float, float] | None:
    try:
        x, y = (float(v) for v in value)  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return None
    return (x, y) if x > 0 and y > 0 and np.isfinite([x, y]).all() else None


def _source_exif(img: Image.Image) -> bytes | None:
    raw = img.info.get("exif")
    if isinstance(raw, bytes) and raw:
        return raw if raw.startswith(_EXIF_HEADER) else _EXIF_HEADER + raw
    # TIFF keeps its tags in the image's own IFD (next to strip offsets etc.),
    # PNG may carry them as a text chunk: rebuild EXIF from the meaningful ones.
    try:
        found = img.getexif()
        clean = Image.Exif()
        for tag in _DESCRIPTIVE_TAGS:
            if tag in found:
                clean[tag] = found[tag]
        for tag in (_EXIF_IFD, _GPS_IFD):
            if tag in found and (sub := found.get_ifd(tag)):
                clean[tag] = dict(sub)
        return clean.tobytes() if len(clean) else None
    except Exception as exc:  # metadata is optional, the pixels are what matter
        log.warning("ignoring unreadable EXIF: %s", exc)
        return None


def _icc_space(icc: bytes | None) -> bytes | None:
    """Colour space signature from the ICC header ("RGB ", "GRAY", "CMYK", ...)."""
    return icc[16:20] if icc is not None and len(icc) >= 128 else None


def _to_rgb(img: Image.Image, icc: bytes | None) -> tuple[Image.Image, bytes | None]:
    """8-bit RGB; alpha is flattened onto white. Returns the ICC that still fits."""
    if img.mode in ("I;16", "I;16B", "I;16L", "I;16N", "I"):  # 16-bit grey
        img = Image.fromarray((np.clip(np.asarray(img), 0, 65535) >> 8).astype(np.uint8))
    elif img.mode == "F":
        values = np.nan_to_num(np.asarray(img, dtype=np.float32))
        scale = 255.0 if values.max(initial=0.0) <= 1.0 else 1.0
        img = Image.fromarray(np.clip(values * scale + 0.5, 0, 255).astype(np.uint8))
    space = _icc_space(icc)
    if img.mode == "CMYK" and space == b"CMYK" and icc is not None:
        try:
            srgb = ImageCms.createProfile("sRGB")
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            converted = ImageCms.profileToProfile(img, src, srgb, outputMode="RGB")
            if converted is not None:
                return converted, ImageCms.ImageCmsProfile(srgb).tobytes()
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            log.warning("CMYK profile conversion failed: %s", exc)
    if space is not None and space != b"RGB ":
        icc = None  # a grey/CMYK profile would mislabel the RGB result
    if img.has_transparency_data:
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat, icc
    return (img if img.mode == "RGB" else img.convert("RGB")), icc


# --- saving -------------------------------------------------------------------


def output_path(src: Path, ext: str | None = None) -> Path:
    """First free `<stem>-mirage[-N].<ext>` next to `src`.

    `ext` defaults to the source's own (HEIC/HEIF become jpg, same letter case).
    A source that is itself a Mirage result gets a sibling number, not
    `-mirage-mirage`.
    """
    src = Path(src)
    if ext is None:
        ext = src.suffix[1:]
        if ext.lower() in ("heic", "heif"):
            ext = "JPG" if ext.isupper() else "jpg"
    ext = ext.lstrip(".")
    suffix = f".{ext}" if ext else ""
    base = _OUTPUT_STEM.sub("", src.stem)
    for n in itertools.count(1):
        tag = "-mirage" if n == 1 else f"-mirage-{n}"
        candidate = src.with_name(f"{base}{tag}{suffix}")
        if not os.path.lexists(candidate):  # case-insensitive on APFS, as Finder sees it
            return candidate
    raise AssertionError("unreachable")


def save_image(image_bgr: np.ndarray, src: Path, meta: PhotoMeta) -> Path:
    """Write the result next to `src` and return its path.

    JPEG 95 (4:4:4) for JPEG/HEIC sources, PNG, WebP 95, TIFF or BMP otherwise.
    The file appears atomically under a free name; nothing existing is replaced.
    """
    src = Path(src)
    array = np.asarray(image_bgr)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3 or array.size == 0:
        raise ValueError(f"expected an HxWx3 uint8 BGR image, got {array.dtype} {array.shape}")
    img = Image.fromarray(cv2.cvtColor(array, cv2.COLOR_BGR2RGB))
    fmt = meta.format if meta.format in _FORMAT_EXTS else "png"
    pil_format, options = _encoder(fmt, meta, _output_exif(meta.exif, img.size))
    ext = _output_ext(src, fmt)

    # Hidden temp name in the same folder: O_EXCL, normal permissions, same volume.
    tmp = src.with_name(f".{src.stem}-mirage.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "xb") as fh:
            img.save(fh, format=pil_format, **options)
            fh.flush()
            os.fsync(fh.fileno())
        return _publish(tmp, src, ext)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _output_ext(src: Path, fmt: str) -> str | None:
    """None keeps the source's extension; otherwise the format's usual one."""
    source_ext = src.suffix[1:]
    allowed = _FORMAT_EXTS[fmt]
    if source_ext.lower() in allowed:
        return None
    return allowed[0].upper() if source_ext.isupper() else allowed[0]


def _encoder(fmt: str, meta: PhotoMeta, exif: bytes | None) -> tuple[str, dict[str, Any]]:
    options: dict[str, Any] = {}
    if meta.icc_profile:
        options["icc_profile"] = meta.icc_profile
    if meta.dpi:
        options["dpi"] = meta.dpi
    if fmt in ("jpeg", "heic"):
        if exif is not None and len(exif) > _JPEG_MAX_EXIF:
            log.warning("EXIF too large for JPEG (%d bytes), dropped", len(exif))
            exif = None
        options.update(quality=JPEG_QUALITY, subsampling=0)  # 0 = 4:4:4
        pil_format = "JPEG"
    elif fmt == "png":
        options.update(optimize=True)
        pil_format = "PNG"
    elif fmt == "webp":
        options.update(quality=WEBP_QUALITY)  # WebP has no DPI; Pillow ignores it
        pil_format = "WEBP"
    elif fmt == "tiff":
        # libtiff (used for compressed TIFF) cannot write the EXIF/GPS sub-IFDs,
        # so a TIFF with EXIF is written uncompressed by Pillow's own writer.
        options.update(compression="raw" if exif else "tiff_lzw")
        pil_format = "TIFF"
    else:  # bmp: no ICC or EXIF in the format
        options.pop("icc_profile", None)
        return "BMP", options
    if exif:
        options["exif"] = exif
    return pil_format, options


_SOFTWARE, _DESCRIPTION = 0x0131, 0x010E


def _mark_synthetic(exif) -> None:
    """Say plainly in the file that its faces were swapped (see docs/RESPONSIBLE_USE.md)."""
    from mirage import __version__

    exif[_SOFTWARE] = f"Mirage {__version__} (face swap)"
    exif[_DESCRIPTION] = "Faces swapped with Mirage - not an original photo"


def _output_exif(raw: bytes | None, size: tuple[int, int]) -> bytes | None:
    """Source EXIF made true for the saved pixels: upright, real size, no stale
    thumbnail, and marked as face-swapped."""
    if not raw:
        exif = Image.Exif()
        _mark_synthetic(exif)
        return exif.tobytes()
    try:
        exif = Image.Exif()
        exif.load(raw)
        exif[_ORIENTATION] = 1
        _mark_synthetic(exif)
        if _EXIF_IFD in exif:
            sub = exif.get_ifd(_EXIF_IFD)
            for tag, value in ((_EXIF_WIDTH, size[0]), (_EXIF_HEIGHT, size[1])):
                if tag in sub:
                    sub[tag] = value
        # Re-serialising leaves out IFD1, the thumbnail that still shows the original.
        return exif.tobytes()
    except Exception as exc:  # Pillow cannot parse or re-serialise every camera's EXIF
        log.warning("cannot rewrite EXIF (%s), patching it in place", exc)
        return _patch_exif(raw)


def _patch_exif(raw: bytes) -> bytes | None:
    """Fallback: set Orientation to 1 and unlink the thumbnail IFD in the raw bytes."""
    data = bytearray(raw if raw.startswith(_EXIF_HEADER) else _EXIF_HEADER + raw)
    base = len(_EXIF_HEADER)
    try:
        order = {b"II": "<", b"MM": ">"}[bytes(data[base : base + 2])]
        (ifd0,) = struct.unpack_from(order + "I", data, base + 4)
        start = base + ifd0
        (count,) = struct.unpack_from(order + "H", data, start)
        for i in range(count):
            entry = start + 2 + 12 * i
            tag, kind = struct.unpack_from(order + "HH", data, entry)
            if tag == _ORIENTATION and kind == 3:  # SHORT, value inline
                struct.pack_into(order + "H", data, entry + 8, 1)
        struct.pack_into(order + "I", data, start + 2 + 12 * count, 0)
    except (KeyError, struct.error):
        log.warning("unreadable EXIF dropped")
        return None
    return bytes(data)


def _publish(tmp: Path, src: Path, ext: str | None) -> Path:
    """Give the finished temp file its final name without replacing anything."""
    for _ in range(1000):
        dest = output_path(src, ext)
        try:
            os.link(tmp, dest)  # fails, rather than overwrites, if the name got taken
        except FileExistsError:
            continue
        except OSError:  # no hard links on this volume (exFAT, some shares)
            os.replace(tmp, dest)
            return dest
        with contextlib.suppress(OSError):  # the result is in place; a stray hidden temp is harmless
            tmp.unlink()
        return dest
    raise FileExistsError(f"no free output name next to {src}")
