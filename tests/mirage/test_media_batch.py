import threading
from pathlib import Path

import numpy as np

from mirage.media import batch
from mirage.media.types import RenderOptions, TargetFace


def _target(i):
    return TargetFace(index=i, bbox=(0, 0, 10, 10), kps=np.zeros((5, 2), np.float32), score=0.9,
                      embedding=np.ones(512, np.float32))


def _fakes(faces_per_file, fail_on=None):
    saved = []

    def load(path):
        if path.name == fail_on:
            raise ValueError("not an image")
        return np.zeros((20, 30, 3), np.uint8), {"src": path.name}

    def analyze(image):
        return [_target(i + 1) for i in range(faces_per_file.pop(0))]

    def render(image, targets, plan, embeddings, options):
        return image + 1

    def save(image, src, meta):
        out = src.with_name(src.stem + "-mirage.jpg")
        saved.append(out)
        return out

    return dict(load=load, analyze=analyze, render=render, save=save), saved


def plan_main(targets, size):
    return {t.index: ("sam" if t.index == 1 else None) for t in targets}


def test_statuses_for_saved_no_face_and_failed(tmp_path: Path):
    items = [batch.BatchItem(tmp_path / n) for n in ("a.jpg", "b.jpg", "bad.jpg")]
    fakes, saved = _fakes([2, 0], fail_on="bad.jpg")
    updates = []
    batch.run_batch(items, plan_main, {"sam": np.ones(512)}, RenderOptions(),
                    on_update=lambda i, it: updates.append((i, it.status)), **fakes)
    assert [it.status for it in items] == [batch.SAVED, batch.NO_FACE, batch.FAILED]
    assert items[0].output == tmp_path / "a-mirage.jpg" and items[0].swapped == 1 and items[0].faces == 2
    assert items[2].error == "not an image"
    assert (0, batch.WORKING) in updates and (0, batch.SAVED) in updates


def test_empty_plan_is_skipped_not_failed(tmp_path: Path):
    items = [batch.BatchItem(tmp_path / "a.jpg")]
    fakes, saved = _fakes([1])
    batch.run_batch(items, lambda targets, size: {t.index: None for t in targets}, {}, RenderOptions(), **fakes)
    assert items[0].status == batch.SKIPPED and saved == []


def test_cancel_leaves_the_rest_waiting(tmp_path: Path):
    cancel = threading.Event()
    items = [batch.BatchItem(tmp_path / f"{n}.jpg") for n in "abc"]
    fakes, _ = _fakes([1, 1, 1])

    def on_update(i, item):
        if item.status == batch.SAVED:
            cancel.set()

    batch.run_batch(items, plan_main, {"sam": np.ones(512)}, RenderOptions(), on_update=on_update, cancel=cancel, **fakes)
    assert [it.status for it in items] == [batch.SAVED, batch.WAITING, batch.WAITING]
