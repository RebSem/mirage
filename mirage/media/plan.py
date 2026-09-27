"""Who becomes whom: the automatic plan and face suggestions (pure numpy)."""

from __future__ import annotations

import math

import numpy as np

from mirage.media.types import Plan, SourceInfo, TargetFace

ME_THRESHOLD = 0.40      # cosine similarity for "this is the same person"
NEAR_TIE = 0.15          # faces within 15 % of the largest area count as equally big
AGE_SCALE = 12.0         # years; how quickly age difference lowers a suggestion
SUGGEST_MIN = 0.55       # score needed for the "suggested" mark


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def number_left_to_right(targets: list[TargetFace]) -> list[TargetFace]:
    """Stable numbering users can talk about: 1, 2, 3… from left to right."""
    ordered = sorted(targets, key=lambda t: (t.center[0], t.center[1]))
    for i, t in enumerate(ordered, start=1):
        t.index = i
    return ordered


def main_face(targets: list[TargetFace], image_size: tuple[int, int]) -> int | None:
    """Index of the main face: the largest; on near-ties, the one closest to the centre."""
    if not targets:
        return None
    biggest = max(t.area for t in targets)
    contenders = [t for t in targets if t.area >= biggest * (1 - NEAR_TIE)]
    cx, cy = image_size[0] / 2, image_size[1] / 2
    best = min(contenders, key=lambda t: math.hypot(t.center[0] - cx, t.center[1] - cy))
    return best.index


def find_me(targets: list[TargetFace], me_embedding: np.ndarray | None) -> int | None:
    """Index of the face that is you (best match above the threshold), if any."""
    if me_embedding is None or not targets:
        return None
    scored = [(cosine(t.embedding, me_embedding), t.index) for t in targets]
    score, index = max(scored)
    return index if score >= ME_THRESHOLD else None


def auto_plan(targets: list[TargetFace], image_size: tuple[int, int], selected_id: str | None,
              me_embedding: np.ndarray | None = None, selected_is_me: bool = False) -> Plan:
    """Swap you if you're in the picture, else the main face; leave everyone else alone."""
    plan: Plan = {t.index: None for t in targets}
    if selected_id is None or not targets:
        return plan
    # Wearing your own face: "find me" would swap you onto yourself.
    chosen = None if selected_is_me else find_me(targets, me_embedding)
    if chosen is None:
        chosen = main_face(targets, image_size)
    if chosen is not None:
        plan[chosen] = selected_id
    return plan


def swap_everyone(targets: list[TargetFace], selected_id: str | None) -> Plan:
    return {t.index: selected_id for t in targets}


def suggestion_score(target: TargetFace, source: SourceInfo) -> float:
    """0..1: how natural this source is likely to look on this target (gender, then age)."""
    if target.gender is None or source.gender is None:
        gender = 0.6
    else:
        gender = 1.0 if int(target.gender) == int(source.gender) else 0.2
    if target.age is None or source.age is None:
        age = 0.7
    else:
        age = math.exp(-abs(float(target.age) - float(source.age)) / AGE_SCALE)
    return round(0.65 * gender + 0.35 * age, 4)


def rank_sources(target: TargetFace, sources: list[SourceInfo]) -> list[tuple[SourceInfo, float, bool]]:
    """Library faces best-first for this target: (source, score, suggested)."""
    scored = [(s, suggestion_score(target, s), i) for i, s in enumerate(sources)]
    scored.sort(key=lambda x: (-x[1], x[2]))
    top = [s for s in scored[:2] if s[1] >= SUGGEST_MIN]
    top_ids = {s[0].id for s in top}
    return [(s, score, s.id in top_ids) for s, score, _i in scored]


def assigned_count(plan: Plan) -> int:
    return sum(1 for v in plan.values() if v)
