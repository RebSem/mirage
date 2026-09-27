import numpy as np

from mirage.media.plan import (
    auto_plan,
    cosine,
    find_me,
    main_face,
    number_left_to_right,
    rank_sources,
    suggestion_score,
    swap_everyone,
)
from mirage.media.types import SourceInfo, TargetFace

W, H = 1000, 600


def face(x, y, size, emb=None, gender=None, age=None, index=0):
    e = np.zeros(512, np.float32) if emb is None else np.asarray(emb, np.float32)
    return TargetFace(index=index, bbox=(x, y, x + size, y + size), kps=np.zeros((5, 2), np.float32),
                      score=0.9, embedding=e, gender=gender, age=age)


def unit(i):
    v = np.zeros(512, np.float32)
    v[i] = 1.0
    return v


def test_numbering_left_to_right():
    faces = number_left_to_right([face(700, 100, 50), face(100, 100, 50), face(400, 100, 50)])
    assert [f.index for f in faces] == [1, 2, 3]
    assert [f.bbox[0] for f in faces] == [100, 400, 700]


def test_main_face_is_largest():
    faces = number_left_to_right([face(50, 50, 300), face(600, 200, 120)])
    assert main_face(faces, (W, H)) == 1


def test_near_tie_prefers_the_centre():
    faces = number_left_to_right([face(0, 0, 200), face(400, 200, 195)])  # 5 % smaller, but central
    assert main_face(faces, (W, H)) == 2


def test_find_me_needs_a_real_match():
    faces = number_left_to_right([face(100, 100, 100, unit(0)), face(500, 100, 100, unit(1))])
    assert find_me(faces, unit(1)) == 2
    assert find_me(faces, unit(7)) is None
    assert find_me(faces, None) is None


def test_auto_plan_prefers_me_over_the_main_face():
    faces = number_left_to_right([face(50, 50, 300, unit(0)), face(600, 200, 100, unit(1))])
    assert auto_plan(faces, (W, H), "alex", me_embedding=unit(1)) == {1: None, 2: "alex"}
    assert auto_plan(faces, (W, H), "alex") == {1: "alex", 2: None}


def test_auto_plan_without_a_selected_face_is_empty():
    faces = number_left_to_right([face(50, 50, 300)])
    assert auto_plan(faces, (W, H), None) == {1: None}
    assert auto_plan([], (W, H), "alex") == {}


def test_swap_everyone():
    faces = number_left_to_right([face(50, 50, 100), face(300, 50, 100)])
    assert swap_everyone(faces, "sam") == {1: "sam", 2: "sam"}


def test_suggestions_prefer_same_gender_then_close_age():
    target = face(0, 0, 100, gender=0, age=30)
    sources = [SourceInfo("m", "Mark", gender=1, age=30), SourceInfo("f60", "Fay", gender=0, age=60),
               SourceInfo("f28", "Ann", gender=0, age=28), SourceInfo("u", "Unknown")]
    ranked = rank_sources(target, sources)
    assert [s.id for s, _score, _sug in ranked][:2] == ["f28", "f60"]
    assert ranked[0][2] is True                       # marked as suggested
    assert suggestion_score(target, sources[0]) < suggestion_score(target, sources[3])


def test_cosine_handles_zero_vectors():
    assert cosine(np.zeros(4), np.ones(4)) == 0.0
    assert abs(cosine(np.ones(4), np.ones(4)) - 1.0) < 1e-6
