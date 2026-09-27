"""Batch: the automatic plan applied to many photos, each saved next to its original."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mirage.media.types import Plan, RenderOptions, TargetFace

log = logging.getLogger(__name__)

WAITING, WORKING, SAVED, NO_FACE, SKIPPED, FAILED = "waiting", "working", "saved", "no_face", "skipped", "failed"


@dataclass
class BatchItem:
    path: Path
    status: str = WAITING
    output: Path | None = None
    error: str | None = None
    faces: int = 0
    swapped: int = 0


def run_batch(items: list[BatchItem],
              plan_for: Callable[[list[TargetFace], tuple[int, int]], Plan],
              embeddings: dict[str, np.ndarray],
              options: RenderOptions,
              on_update: Callable[[int, BatchItem], None] | None = None,
              cancel: threading.Event | None = None,
              analyze=None, render=None, load=None, save=None) -> list[BatchItem]:
    """Process items in order; stops early (leaving the rest WAITING) when cancelled.

    analyze/render/load/save default to the real pipeline and can be replaced in tests.
    """
    from mirage.power import AwakeGuard

    if analyze is None:
        from mirage.media.analyze import analyze_image as analyze
    if render is None:
        from mirage.media.render import PhotoRenderer

        render = PhotoRenderer().render
    if load is None or save is None:
        from mirage.media import photo_io

        load = load or photo_io.load_image
        save = save or photo_io.save_image

    awake = AwakeGuard()
    awake.hold("Mirage is swapping faces in photos")
    try:
        for i, item in enumerate(items):
            if cancel is not None and cancel.is_set():
                break
            item.status = WORKING
            if on_update:
                on_update(i, item)
            try:
                image, meta = load(item.path)
                targets = analyze(image)
                item.faces = len(targets)
                if not targets:
                    item.status = NO_FACE
                else:
                    plan = plan_for(targets, (image.shape[1], image.shape[0]))
                    item.swapped = sum(1 for v in plan.values() if v)
                    if item.swapped == 0:
                        item.status = SKIPPED
                    else:
                        result = render(image, targets, plan, embeddings, options)
                        item.output = save(result, item.path, meta)
                        item.status = SAVED
            except Exception as exc:
                log.exception("batch item failed: %s", item.path)
                item.status, item.error = FAILED, str(exc)
            if on_update:
                on_update(i, item)
    finally:
        awake.release()
    return items
