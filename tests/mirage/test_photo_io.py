"""Photo file handling: upright loading, metadata-preserving saves, file discovery."""

from __future__ import annotations

import hashlib
import io
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import ExifTags, Image, ImageCms, JpegImagePlugin

from mirage.media import photo_io
from mirage.media.photo_io import (
    PhotoMeta,
    collect_media,
    is_image,
    is_video,
    load_image,
    output_path,
    save_image,
)

DATE = "2024:05:06 07:08:09"
HAS_SIPS = sys.platform == "darwin" and os.access("/usr/bin/sips", os.X_OK)

RED_BGR = (0, 0, 255)
BLUE_BGR = (255, 0, 0)


def _srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _exif(orientation: int | None = None, width: int | None = None, height: int | None = None) -> bytes:
    """Raw EXIF (bytes, so Pillow's TIFF writer keeps the Exif sub-IFD too)."""
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    if orientation is not None:
        exif[0x0112] = orientation
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = DATE  # DateTimeOriginal
    if width is not None and height is not None:
        sub[0xA002], sub[0xA003] = width, height
    return exif.tobytes()


def _marked(width: int = 60, height: int = 40) -> Image.Image:
    """Blue RGB picture with a red square in the top-left corner (as stored)."""
    pixels = np.zeros((height, width, 3), np.uint8)
    pixels[:] = (0, 0, 255)
    pixels[:12, :12] = (255, 0, 0)
    return Image.fromarray(pixels)


def _write(path: Path, image: Image.Image | None = None, **options: object) -> Path:
    (image or _marked()).save(path, **options)
    return path


def _near(pixel: np.ndarray, bgr: tuple[int, int, int], tol: int = 40) -> bool:
    return bool(np.all(np.abs(pixel.astype(int) - np.array(bgr)) <= tol))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- extensions & discovery ---------------------------------------------------


def test_extension_checks_ignore_case() -> None:
    assert is_image("a/B.JPG") and is_image(Path("x.HeIc")) and is_image("scan.tiff")
    assert is_video("clip.MOV") and is_video(Path("x.webm"))
    assert not is_image("clip.mp4") and not is_video("photo.jpg")
    assert not is_image("jpg") and not is_image("notes.txt")


def test_collect_media_folders_files_and_order(tmp_path: Path) -> None:
    album = tmp_path / "album"
    (album / "nested").mkdir(parents=True)
    for name in ("img10.png", "img2.jpg", "IMG1.jpeg", "clip.MOV", "a.mp4", "notes.txt",
                 ".hidden.jpg", "._img2.jpg", "img2-mirage.jpg", "img2-mirage-3.jpg",
                 "nested/deep.jpg"):
        (album / name).write_bytes(b"x")
    loose = tmp_path / "loose.webp"
    loose.write_bytes(b"x")
    earlier = tmp_path / "old-mirage.jpg"  # named explicitly, so it is wanted
    earlier.write_bytes(b"x")

    images, videos = collect_media([
        album,
        album / "img2.jpg",              # duplicate of a folder child
        tmp_path / "album" / ".." / "album" / "img10.png",
        loose,
        earlier,
        tmp_path / "missing.jpg",
        tmp_path / "notes.txt",
    ])

    assert [p.name for p in images] == ["IMG1.jpeg", "img2.jpg", "img10.png", "loose.webp", "old-mirage.jpg"]
    assert [p.name for p in videos] == ["a.mp4", "clip.MOV"]
    assert all(p.is_absolute() for p in images + videos)


def test_collect_media_empty_inputs(tmp_path: Path) -> None:
    assert collect_media([]) == ([], [])
    assert collect_media([tmp_path]) == ([], [])


# --- output names -------------------------------------------------------------


def test_output_path_is_unique_and_next_to_source(tmp_path: Path) -> None:
    src = tmp_path / "photo.jpg"
    src.write_bytes(b"x")
    first = output_path(src)
    assert first == tmp_path / "photo-mirage.jpg"
    first.write_bytes(b"x")
    second = output_path(src)
    assert second == tmp_path / "photo-mirage-2.jpg"
    second.write_bytes(b"x")
    assert output_path(src) == tmp_path / "photo-mirage-3.jpg"
    assert output_path(src, "png") == tmp_path / "photo-mirage.png"
    assert output_path(src, ".webp") == tmp_path / "photo-mirage.webp"


def test_output_path_heic_becomes_jpg(tmp_path: Path) -> None:
    assert output_path(tmp_path / "IMG_0001.heic") == tmp_path / "IMG_0001-mirage.jpg"
    assert output_path(tmp_path / "IMG_0002.HEIC") == tmp_path / "IMG_0002-mirage.JPG"
    assert output_path(tmp_path / "x.heif") == tmp_path / "x-mirage.jpg"
    assert output_path(tmp_path / "IMG_0003.JPG") == tmp_path / "IMG_0003-mirage.JPG"


def test_output_path_for_an_earlier_result(tmp_path: Path) -> None:
    src = tmp_path / "photo-mirage.jpg"
    src.write_bytes(b"x")
    assert output_path(src) == tmp_path / "photo-mirage-2.jpg"


# --- loading ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "fmt", "options"),
    [
        ("p.jpg", "jpeg", {"quality": 95}),
        ("p.png", "png", {}),
        ("p.webp", "webp", {"lossless": True}),
        ("p.tif", "tiff", {}),
    ],
)
def test_load_applies_exif_orientation(tmp_path: Path, name: str, fmt: str, options: dict) -> None:
    src = _write(tmp_path / name, exif=_exif(orientation=6), **options)
    image, meta = load_image(src)
    # Orientation 6 = shown rotated 90° clockwise: 60x40 stored -> 40 wide, 60 high,
    # and the stored top-left corner ends up top-right.
    assert image.shape == (60, 40, 3) and image.dtype == np.uint8
    assert image.flags.c_contiguous
    assert _near(image[3, -4], RED_BGR) and _near(image[3, 3], BLUE_BGR) and _near(image[-4, -4], BLUE_BGR)
    assert meta.format == fmt
    assert meta.exif is not None and meta.exif.startswith(b"Exif\x00\x00")


def test_load_without_orientation_keeps_pixels(tmp_path: Path) -> None:
    src = _write(tmp_path / "p.png")
    image, meta = load_image(src)
    assert image.shape == (40, 60, 3)
    assert tuple(image[0, 0]) == RED_BGR and tuple(image[-1, -1]) == BLUE_BGR
    assert meta == PhotoMeta(format="png", exif=None, icc_profile=None, dpi=meta.dpi)


def test_load_png_with_alpha_flattens_onto_white(tmp_path: Path) -> None:
    rgba = np.zeros((10, 20, 4), np.uint8)
    rgba[:, :10] = (255, 0, 0, 255)  # opaque red
    rgba[:, 10:] = (0, 255, 0, 0)    # fully transparent green
    src = _write(tmp_path / "a.png", Image.fromarray(rgba, "RGBA"))
    image, meta = load_image(src)
    assert image.shape == (10, 20, 3) and image.dtype == np.uint8
    assert tuple(image[5, 2]) == RED_BGR
    assert tuple(image[5, 15]) == (255, 255, 255)
    assert meta.format == "png"


def test_load_palette_and_grey_images(tmp_path: Path) -> None:
    palette = _marked().convert("P", palette=Image.Palette.ADAPTIVE, colors=4)
    image, _ = load_image(_write(tmp_path / "p.png", palette))
    assert image.shape == (40, 60, 3) and tuple(image[0, 0]) == RED_BGR
    grey = Image.fromarray(np.full((8, 8), 77, np.uint8), "L")
    image, meta = load_image(_write(tmp_path / "g.jpg", grey))
    assert image.shape == (8, 8, 3) and np.all(np.abs(image.astype(int) - 77) <= 2)
    assert meta.format == "jpeg"


def test_load_16_bit_grey_png(tmp_path: Path) -> None:
    values = np.zeros((4, 8), np.uint16)
    values[:, :4] = 65535
    values[:, 4:] = 32768
    src = _write(tmp_path / "g16.png", Image.fromarray(values))
    assert Image.open(src).mode.startswith("I;16")
    image, _ = load_image(src)
    assert image.dtype == np.uint8 and image.shape == (4, 8, 3)
    assert tuple(image[0, 0]) == (255, 255, 255) and tuple(image[0, 7]) == (128, 128, 128)


def test_load_16_bit_colour_png(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    bgr16 = np.zeros((4, 8, 3), np.uint16)
    bgr16[..., 2] = 65535  # red
    bgr16[..., 1] = 32768
    src = tmp_path / "c16.png"
    assert cv2.imwrite(str(src), bgr16)
    image, _ = load_image(src)
    assert image.dtype == np.uint8 and tuple(image[0, 0]) == (0, 128, 255)


def test_load_cmyk_jpeg_gives_bgr(tmp_path: Path) -> None:
    cmyk = Image.new("CMYK", (16, 16), (0, 255, 255, 0))  # red ink
    image, meta = load_image(_write(tmp_path / "c.jpg", cmyk))
    assert image.shape == (16, 16, 3) and _near(image[8, 8], RED_BGR)
    assert meta.format == "jpeg"


def test_load_detects_format_by_content(tmp_path: Path) -> None:
    src = _write(tmp_path / "really-a-png.jpg", format="PNG")
    _, meta = load_image(src)
    assert meta.format == "png"


@pytest.mark.parametrize("content", [b"", b"hello, not a picture", b"\xff\xd8\xff\xe0broken"])
def test_load_unreadable_raises_value_error(tmp_path: Path, content: bytes) -> None:
    src = tmp_path / "bad.jpg"
    src.write_bytes(content)
    with pytest.raises(ValueError, match="not an image"):
        load_image(src)


def test_load_missing_or_folder_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not an image"):
        load_image(tmp_path / "missing.png")
    with pytest.raises(ValueError, match="not an image"):
        load_image(tmp_path)


def test_load_bad_heic_raises_value_error(tmp_path: Path) -> None:
    src = tmp_path / "bad.heic"  # goes through sips on macOS, straight to the error elsewhere
    src.write_bytes(b"\x00\x00\x00\x18ftypheic garbage")
    with pytest.raises(ValueError, match="not an image"):
        load_image(src)


# --- saving -------------------------------------------------------------------


def test_save_jpeg_keeps_metadata_and_resets_orientation(tmp_path: Path) -> None:
    icc = _srgb_icc()
    src = _write(tmp_path / "photo.jpg", exif=_exif(orientation=6, width=60, height=40),
                 icc_profile=icc, dpi=(300, 300), quality=95)
    before = _sha(src)
    image, meta = load_image(src)
    assert meta.icc_profile == icc and meta.dpi == (300.0, 300.0)

    out = save_image(image, src, meta)

    assert out == tmp_path / "photo-mirage.jpg"
    assert _sha(src) == before
    with Image.open(out) as saved:
        assert saved.format == "JPEG" and saved.size == (40, 60)
        assert JpegImagePlugin.get_sampling(saved) == 0  # 4:4:4
        assert saved.info.get("icc_profile") == icc
        assert saved.info.get("dpi") == (300, 300)
        exif = saved.getexif()
        assert exif[0x0112] == 1
        assert exif[0x010F] == "TestCam"
        sub = exif.get_ifd(0x8769)
        assert sub[0x9003] == DATE
        assert (sub[0xA002], sub[0xA003]) == (40, 60)  # upright size
    # Reloading the result must not rotate again.
    again, _ = load_image(out)
    assert again.shape == image.shape
    assert _near(again[3, -4], RED_BGR)


@pytest.mark.parametrize(
    ("name", "pil_format", "options"),
    [
        ("p.png", "PNG", {}),
        ("p.webp", "WEBP", {"quality": 90}),
        ("p.tiff", "TIFF", {}),
    ],
)
def test_save_keeps_format_and_metadata(tmp_path: Path, name: str, pil_format: str, options: dict) -> None:
    icc = _srgb_icc()
    src = _write(tmp_path / name, exif=_exif(orientation=8), icc_profile=icc, **options)
    image, meta = load_image(src)
    assert image.shape == (60, 40, 3)

    out = save_image(image, src, meta)

    assert out.name == f"p-mirage{src.suffix}"
    with Image.open(out) as saved:
        assert saved.format == pil_format and saved.size == (40, 60)
        assert saved.info.get("icc_profile") == icc
        exif = saved.getexif()
        assert exif.get(0x0112) == 1
        assert exif.get_ifd(0x8769).get(0x9003) == DATE


def test_save_png_result_is_lossless(tmp_path: Path) -> None:
    src = _write(tmp_path / "p.png")
    image, meta = load_image(src)
    out = save_image(image, src, meta)
    again, _ = load_image(out)
    assert np.array_equal(again, image)


def test_save_bmp(tmp_path: Path) -> None:
    src = _write(tmp_path / "p.bmp")
    image, meta = load_image(src)
    assert meta.format == "bmp"
    out = save_image(image, src, meta)
    assert out.name == "p-mirage.bmp"
    with Image.open(out) as saved:
        assert saved.format == "BMP"


def test_save_never_overwrites_and_cleans_up(tmp_path: Path) -> None:
    src = _write(tmp_path / "photo.jpg", quality=95)
    before = _sha(src)
    image, meta = load_image(src)
    image[:] = 0
    first = save_image(image, src, meta)
    second = save_image(image, src, meta)
    assert (first.name, second.name) == ("photo-mirage.jpg", "photo-mirage-2.jpg")
    assert _sha(src) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo-mirage-2.jpg", "photo-mirage.jpg", "photo.jpg"]


def test_save_heic_source_as_jpeg(tmp_path: Path) -> None:
    src = tmp_path / "IMG_0001.HEIC"
    src.write_bytes(b"placeholder")
    image = np.full((20, 30, 3), 128, np.uint8)
    meta = PhotoMeta(format="heic", exif=_exif(orientation=6), icc_profile=_srgb_icc(), dpi=(72.0, 72.0))
    out = save_image(image, src, meta)
    assert out == tmp_path / "IMG_0001-mirage.JPG"
    with Image.open(out) as saved:
        assert saved.format == "JPEG" and saved.size == (30, 20)
        assert saved.getexif()[0x0112] == 1


def test_save_uses_real_format_extension(tmp_path: Path) -> None:
    src = _write(tmp_path / "really-a-png.jpg", format="PNG")
    image, meta = load_image(src)
    out = save_image(image, src, meta)
    assert out.name == "really-a-png-mirage.png"
    with Image.open(out) as saved:
        assert saved.format == "PNG"


def test_save_patches_exif_when_pillow_cannot_rewrite_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _write(tmp_path / "photo.jpg", exif=_exif(orientation=6))
    image, meta = load_image(src)

    def fail(*_args: object, **_kwargs: object) -> bytes:
        raise ValueError("unsupported tag")

    monkeypatch.setattr(Image.Exif, "tobytes", fail)
    out = save_image(image, src, meta)
    monkeypatch.undo()
    with Image.open(out) as saved:
        exif = saved.getexif()
        assert exif[0x0112] == 1
        assert exif.get_ifd(0x8769)[0x9003] == DATE


def _exif_with_thumbnail(thumb: bytes) -> bytes:
    """Little-endian EXIF: IFD0 {Orientation 6} -> IFD1 pointing at a JPEG thumbnail."""
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, 6, 0) + struct.pack("<I", 26)
    ifd1 = (struct.pack("<H", 2) + struct.pack("<HHII", 0x0201, 4, 1, 56)
            + struct.pack("<HHII", 0x0202, 4, 1, len(thumb)) + struct.pack("<I", 0))
    return b"Exif\x00\x00" + b"II*\x00" + struct.pack("<I", 8) + ifd0 + ifd1 + thumb


@pytest.mark.parametrize("pillow_can_rewrite", [True, False])
def test_save_drops_the_original_thumbnail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pillow_can_rewrite: bool
) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, format="JPEG", comment=b"ORIGINAL-FACE")
    thumb = buf.getvalue()
    src = _write(tmp_path / "photo.jpg", exif=_exif_with_thumbnail(thumb), quality=95)
    with Image.open(src) as original:
        assert original.getexif().get_ifd(ExifTags.IFD.IFD1)  # the fixture really has one
    image, meta = load_image(src)
    assert image.shape == (60, 40, 3)
    if not pillow_can_rewrite:
        monkeypatch.setattr(photo_io, "_output_exif", lambda raw, _size: photo_io._patch_exif(raw))

    out = save_image(image, src, meta)

    with Image.open(out) as saved:
        exif = saved.getexif()
        assert exif[0x0112] == 1
        assert not exif.get_ifd(ExifTags.IFD.IFD1)
    if pillow_can_rewrite:
        assert b"ORIGINAL-FACE" not in out.read_bytes()


def test_save_without_hard_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_links(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("operation not permitted")  # like exFAT

    src = _write(tmp_path / "photo.png")
    image, meta = load_image(src)
    monkeypatch.setattr(photo_io.os, "link", no_links)
    names = [save_image(image, src, meta).name for _ in range(2)]
    assert names == ["photo-mirage.png", "photo-mirage-2.png"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo-mirage-2.png", "photo-mirage.png", "photo.png"]


def test_save_rejects_non_bgr_arrays(tmp_path: Path) -> None:
    src = _write(tmp_path / "p.png")
    meta = PhotoMeta(format="png")
    for bad in (np.zeros((4, 4), np.uint8), np.zeros((4, 4, 4), np.uint8), np.zeros((4, 4, 3), np.float32)):
        with pytest.raises(ValueError):
            save_image(bad, src, meta)
    assert [p.name for p in tmp_path.iterdir()] == ["p.png"]


# --- HEIC (macOS only) ----------------------------------------------------------


@pytest.mark.skipif(not HAS_SIPS, reason="needs macOS /usr/bin/sips")
def test_heic_round_trip(tmp_path: Path) -> None:
    jpeg = _write(tmp_path / "seed.jpg", exif=_exif(orientation=6), icc_profile=_srgb_icc(), quality=95)
    heic = tmp_path / "IMG_0001.heic"
    subprocess.run(["/usr/bin/sips", "-s", "format", "heic", str(jpeg), "--out", str(heic)],
                   check=True, capture_output=True, timeout=60)
    jpeg.unlink()

    image, meta = load_image(heic)

    assert meta.format == "heic"
    assert image.shape == (60, 40, 3)
    assert _near(image[3, -4], RED_BGR) and _near(image[-4, 3], BLUE_BGR)
    assert meta.exif is not None and meta.icc_profile

    out = save_image(image, heic, meta)

    assert out == tmp_path / "IMG_0001-mirage.jpg"
    with Image.open(out) as saved:
        assert saved.format == "JPEG" and saved.size == (40, 60)
        exif = saved.getexif()
        assert exif[0x0112] == 1
        assert exif.get_ifd(0x8769)[0x9003] == DATE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["IMG_0001-mirage.jpg", "IMG_0001.heic"]


def test_heic_without_sips_is_not_an_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(photo_io, "SIPS", str(tmp_path / "no-sips"))
    src = tmp_path / "x.heic"
    src.write_bytes(b"\x00\x00\x00\x18ftypheic")
    with pytest.raises(ValueError, match="not an image"):
        load_image(src)
