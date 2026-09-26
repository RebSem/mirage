#!/usr/bin/env bash
# Mirage installer: Python, virtualenv, dependencies, models and OBS.
# Safe to run again at any time; finished steps are skipped.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/venv"
PY_VERSION="3.14"
CLT_DIR="/Library/Developer/CommandLineTools"
STAMP="$VENV/.mirage-requirements.sha256"

WITH_ENHANCER=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: scripts/install.sh [--with-enhancer] [--yes] [--help]

Sets up Mirage in $REPO:
  1. checks macOS, Apple Silicon, Homebrew and the Xcode Command Line Tools
  2. installs Python $PY_VERSION with Homebrew if it is missing
  3. creates ./venv and installs requirements.txt
  4. downloads the face-swap models into ./models and ~/.insightface
  5. checks for OBS, which provides the virtual camera Zoom and Meet see

Options:
  --with-enhancer  also download the GFPGAN face enhancer (~350 MB)
  --yes, -y        answer yes to every question (installs OBS if missing)
  --help, -h       show this help

Running it again is safe: anything already in place is skipped.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-enhancer) WITH_ENHANCER=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# ── output ──────────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; MAGENTA=$'\033[35m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; MAGENTA=""; CYAN=""; RESET=""
fi

TOTAL_STEPS=7
STEP=0
step() { STEP=$((STEP + 1)); printf '\n%s[%d/%d]%s %s%s%s\n' "$MAGENTA" "$STEP" "$TOTAL_STEPS" "$RESET" "$BOLD" "$*" "$RESET"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
info() { printf '  %s•%s %s\n' "$CYAN" "$RESET" "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '\n  %s✗ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

# y/N prompt; --yes answers yes, no terminal answers no.
confirm() {
  local reply
  if [[ $ASSUME_YES -eq 1 ]]; then return 0; fi
  if [[ ! -t 0 ]]; then return 1; fi
  read -r -p "  $1 [y/N] " reply || return 1
  [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

printf '%s✦ Mirage installer%s  %s(real-time face swap for macOS, made for fun)%s\n' "$BOLD" "$RESET" "$DIM" "$RESET"
printf '%s  %s%s\n' "$DIM" "$REPO" "$RESET"

# Keep the Mac awake while we download and compile; ends with this script.
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i -w $$ >/dev/null 2>&1 &
fi

# ── 1. system ───────────────────────────────────────────────────────────────
step "Checking your Mac"
[[ "$(uname -s)" == "Darwin" ]] || die "Mirage's installer is for macOS. On other systems follow the upstream Deep-Live-Cam README."
ok "macOS $(sw_vers -productVersion 2>/dev/null || echo "?")"
ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  ok "Apple Silicon ($(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo arm64))"
else
  die "Mirage needs an Apple Silicon Mac (M1 or newer); this one is $ARCH. Its pinned packages don't install on Intel."
fi
FREE_GB="$(df -g "$REPO" 2>/dev/null | awk 'NR == 2 { print $4 }')"
if [[ -n "$FREE_GB" && "$FREE_GB" -lt 4 ]]; then
  warn "Only ${FREE_GB} GB free; dependencies and models need about 4 GB."
fi

# ── 2. Homebrew + compiler tools ────────────────────────────────────────────
step "Checking Homebrew and developer tools"
if ! command -v brew >/dev/null 2>&1; then
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x "$candidate" ]]; then eval "$("$candidate" shellenv)"; break; fi
  done
fi
if ! command -v brew >/dev/null 2>&1; then
  printf '\n  Homebrew is needed to install Python. Install it with:\n\n'
  # shellcheck disable=SC2016  # printed for the user to copy, not expanded here
  printf '    %s/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"%s\n\n' "$BOLD" "$RESET"
  printf '  then run %smake install%s again.\n' "$BOLD" "$RESET"
  exit 1
fi
ok "Homebrew $(brew --version 2>/dev/null | head -n 1 | awk '{ print $2 }')"
if ! xcode-select -p >/dev/null 2>&1; then
  die "The Xcode Command Line Tools are missing (insightface compiles C++). Run: xcode-select --install"
fi
ok "Command Line Tools at $(xcode-select -p)"

# ── 3. Python ───────────────────────────────────────────────────────────────
step "Checking Python $PY_VERSION"
BREW_PREFIX="$(brew --prefix)"
find_python() {
  local candidate
  for candidate in "$BREW_PREFIX/opt/python@$PY_VERSION/bin/python$PY_VERSION" \
                   "$BREW_PREFIX/bin/python$PY_VERSION" \
                   "$(command -v "python$PY_VERSION" 2>/dev/null || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then echo "$candidate"; return 0; fi
  done
  return 1
}
if ! PYTHON="$(find_python)"; then
  info "Installing python@$PY_VERSION with Homebrew…"
  brew install "python@$PY_VERSION"
  PYTHON="$(find_python)" || die "python$PY_VERSION is still missing after brew install."
fi
ok "$("$PYTHON" --version) at $PYTHON"

# ── 4. virtualenv ───────────────────────────────────────────────────────────
step "Preparing the virtual environment"
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c "import sys" >/dev/null 2>&1; then
  BROKEN="$VENV.broken-$(date +%Y%m%d-%H%M%S)"
  warn "venv is broken (Python was probably upgraded); moving it aside to $(basename "$BROKEN")"
  mv "$VENV" "$BROKEN"
fi
if [[ -x "$VENV/bin/python" ]]; then
  ok "Using existing venv ($("$VENV/bin/python" --version))"
else
  info "Creating ./venv…"
  "$PYTHON" -m venv "$VENV"
  ok "Created venv ($("$VENV/bin/python" --version))"
fi
VPY="$VENV/bin/python"

# ── 5. dependencies ─────────────────────────────────────────────────────────
step "Installing Python packages"
REQ_HASH="$(shasum -a 256 "$REPO/requirements.txt" | awk '{ print $1 }')"
deps_ok() {
  [[ -f "$STAMP" && "$(cat "$STAMP")" == "$REQ_HASH" ]] &&
    "$VPY" -c "import cv2, numpy, onnxruntime, insightface, PySide6, pyvirtualcam, AVFoundation" >/dev/null 2>&1
}
if deps_ok; then
  ok "Already up to date with requirements.txt"
else
  info "This can take a few minutes the first time (insightface is compiled)…"
  "$VPY" -m pip install --quiet --upgrade pip wheel
  # insightface fails to link when xcode-select points at an Xcode older than
  # the installed macOS SDK; the standalone Command Line Tools always match.
  if [[ -x "$CLT_DIR/usr/bin/ld" ]]; then
    DEVELOPER_DIR="$CLT_DIR" "$VPY" -m pip install -r "$REPO/requirements.txt"
  else
    "$VPY" -m pip install -r "$REPO/requirements.txt"
  fi
  echo "$REQ_HASH" > "$STAMP"
  ok "Packages installed"
fi

# ── 6. models ───────────────────────────────────────────────────────────────
step "Downloading models"
MODELS=("inswapper_128_fp16.onnx")
# "Best" quality uses GPEN-BFR-256 (modules/processors/frame/face_enhancer_gpen256.py)
if [[ $WITH_ENHANCER -eq 1 ]]; then MODELS+=("GPEN-BFR-256.onnx"); fi
info "face swap: ${MODELS[*]}; face detection: buffalo_l"
(
  cd "$REPO"
  "$VPY" - "${MODELS[@]}" <<'PY'
import sys

from modules.model_downloader import ensure_insightface_pack, ensure_model

failed = [name for name in sys.argv[1:] if ensure_model(name) is None]
if not ensure_insightface_pack("buffalo_l"):
    failed.append("buffalo_l")
sys.exit(f"could not download: {', '.join(failed)}" if failed else 0)
PY
) || die "Model download failed. Check your connection and run make install again (downloads resume)."
ok "Models ready in ./models and ~/.insightface/models/buffalo_l"
if [[ $WITH_ENHANCER -eq 0 ]]; then
  info "${DIM}Face enhancer skipped; add it later with: scripts/install.sh --with-enhancer${RESET}"
fi

# ── 7. OBS virtual camera ───────────────────────────────────────────────────
step "Checking OBS (virtual camera)"
if [[ -d "/Applications/OBS.app" || -d "$HOME/Applications/OBS.app" ]]; then
  ok "OBS is installed"
else
  info "Mirage sends the swapped video to the ${BOLD}OBS Virtual Camera${RESET}; that is the camera"
  info "you pick in Zoom, Meet or FaceTime. Without OBS you only get the preview."
  if confirm "Install OBS now with 'brew install --cask obs'?"; then
    if brew install --cask obs; then
      ok "OBS installed"
    else
      warn "brew could not install OBS; get it from https://obsproject.com instead."
    fi
  else
    warn "Skipped. Install it later with: brew install --cask obs"
  fi
fi
if [[ -d "/Applications/OBS.app" || -d "$HOME/Applications/OBS.app" ]]; then
  info "First time only: open OBS, click ${BOLD}Start Virtual Camera${RESET} once and allow the"
  info "system extension in System Settings. After that Mirage drives it on its own."
fi

printf '\n%s✦ All set.%s Next steps:\n' "$GREEN$BOLD" "$RESET"
printf '    %smake run%s          start Mirage from the terminal\n' "$BOLD" "$RESET"
printf '    %smake app%s          build dist/Mirage.app (%smake install-app%s puts it in ~/Applications)\n' "$BOLD" "$RESET" "$BOLD" "$RESET"
printf '    %smake classic%s      the original Deep-Live-Cam window\n\n' "$BOLD" "$RESET"
