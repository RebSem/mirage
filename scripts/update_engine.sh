#!/usr/bin/env bash
# Bring upstream Deep-Live-Cam changes into third_party/deep-live-cam.
#
#   scripts/update_engine.sh            # latest hacksider/Deep-Live-Cam main
#   scripts/update_engine.sh <commit>   # a specific upstream commit
#
# Takes upstream's changes between the commit we are based on
# (third_party/deep-live-cam/UPSTREAM_COMMIT) and the new one, and applies
# them on top of Mirage's own changes with a three-way merge. Conflicts are
# left in the files for you to resolve; nothing is committed.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="third_party/deep-live-cam"
UPSTREAM_URL="https://github.com/hacksider/Deep-Live-Cam.git"
cd "$REPO"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Commit or stash your changes first." >&2
  exit 1
fi

BASE="$(tr -d '[:space:]' < "$ENGINE/UPSTREAM_COMMIT")"
echo "Fetching Deep-Live-Cam…"
git fetch --quiet "$UPSTREAM_URL" "${1:-main}"
NEW="$(git rev-parse FETCH_HEAD)"
git cat-file -e "$BASE^{commit}" 2>/dev/null || git fetch --quiet "$UPSTREAM_URL" "$BASE"

if [[ "$BASE" == "$NEW" ]]; then
  echo "Already at ${NEW:0:7}."
  exit 0
fi

# Only the parts Mirage vendors; upstream's README, media and CI stay upstream.
PATHS=(modules locales run.py tkinter_fix.py benchmark_pipeline.py mypi.ini
       tests/test_core_map_faces_fallback.py tests/test_face_analyser_get_one_face.py)
PATCH="$(mktemp)"
trap 'rm -f "$PATCH"' EXIT
git diff --binary "$BASE" "$NEW" -- "${PATHS[@]}" > "$PATCH"

if [[ ! -s "$PATCH" ]]; then
  echo "Upstream changed nothing Mirage uses (${BASE:0:7} → ${NEW:0:7})."
else
  echo "Applying upstream ${BASE:0:7} → ${NEW:0:7}…"
  if ! git apply --3way --directory="$ENGINE" "$PATCH"; then
    echo "Some changes conflict with Mirage's; fix the conflict markers, then commit." >&2
  fi
fi
echo "$NEW" > "$ENGINE/UPSTREAM_COMMIT"
echo "Review with 'git diff', run 'make test', and check requirements.txt against upstream's:"
echo "  git diff $BASE $NEW -- requirements.txt"
