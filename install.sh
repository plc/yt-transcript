#!/usr/bin/env bash
# yt-transcript installer
#
# Installs yt-transcript and its dependencies:
#   - yt-dlp   (via Homebrew on macOS, apt/pipx elsewhere)
#   - ffmpeg   (via Homebrew on macOS, apt elsewhere)
#   - whisper  (openai-whisper, via pipx)
#   - yt-transcript itself (via pipx, from this repo)
#
# Usage:
#   ./install.sh            # install everything, skip what's already present
#   ./install.sh --check    # just report what's installed/missing, don't install
#   ./install.sh --force    # reinstall yt-transcript even if already installed
#
# Idempotent: re-running is safe. Only installs what's missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHECK_ONLY=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

# -------- pretty output --------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

info()  { printf "%s==>%s %s\n" "$BOLD" "$RESET" "$*"; }
ok()    { printf "  %s✓%s %s\n" "$GREEN" "$RESET" "$*"; }
warn()  { printf "  %s!%s %s\n" "$YELLOW" "$RESET" "$*"; }
err()   { printf "  %s✗%s %s\n" "$RED"   "$RESET" "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

# -------- OS detection --------
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *)      PLATFORM=unknown ;;
esac

# -------- ensure pipx --------
ensure_pipx() {
  if have pipx; then
    ok "pipx already installed"
    return
  fi
  info "installing pipx"
  if [ "$PLATFORM" = macos ] && have brew; then
    brew install pipx
  elif [ "$PLATFORM" = linux ] && have apt-get; then
    sudo apt-get update -y && sudo apt-get install -y pipx
  elif have python3; then
    python3 -m pip install --user pipx
  else
    err "no way to install pipx automatically; install it yourself from https://pipx.pypa.io"
    exit 3
  fi
  pipx ensurepath >/dev/null 2>&1 || true
  # Make pipx visible in this shell for the rest of the script.
  export PATH="$HOME/.local/bin:$PATH"
  if ! have pipx; then
    err "pipx installed but not on PATH. Open a new shell and re-run this script."
    exit 3
  fi
  ok "pipx installed"
}

# -------- ensure a brew-style system dep (yt-dlp, ffmpeg) --------
ensure_system_dep() {
  local name="$1"
  if have "$name"; then
    ok "$name already installed ($("$name" --version 2>&1 | head -1))"
    return
  fi
  info "installing $name"
  if [ "$PLATFORM" = macos ]; then
    if have brew; then
      brew install "$name"
    else
      err "Homebrew is required on macOS. Install from https://brew.sh then re-run."
      exit 3
    fi
  elif [ "$PLATFORM" = linux ] && have apt-get; then
    sudo apt-get update -y && sudo apt-get install -y "$name"
  else
    err "don't know how to install $name on this platform; install it manually"
    exit 3
  fi
  ok "$name installed"
}

# -------- ensure a pipx-installed Python package --------
ensure_pipx_pkg() {
  local pkg="$1"    # pip package name, e.g. openai-whisper
  local bin="$2"    # command it provides, e.g. whisper
  if have "$bin"; then
    ok "$bin already installed"
    return
  fi
  info "installing $pkg via pipx (this can take a minute)"
  pipx install "$pkg"
  if ! have "$bin"; then
    export PATH="$HOME/.local/bin:$PATH"
  fi
  if have "$bin"; then
    ok "$bin installed"
  else
    err "$bin still not on PATH after pipx install. Try: pipx ensurepath && restart your shell"
    exit 3
  fi
}

# -------- check-only mode --------
report() {
  for dep in yt-dlp ffmpeg whisper yt-transcript; do
    if have "$dep"; then
      ok "$dep  ($(command -v "$dep"))"
    else
      err "$dep  (missing)"
    fi
  done
}

if [ "$CHECK_ONLY" = 1 ]; then
  info "yt-transcript dependency check"
  report
  exit 0
fi

# -------- install --------
info "yt-transcript installer ($PLATFORM)"

ensure_pipx
ensure_system_dep yt-dlp
ensure_system_dep ffmpeg
ensure_pipx_pkg openai-whisper whisper

if have yt-transcript && [ "$FORCE" != 1 ]; then
  ok "yt-transcript already installed ($(yt-transcript --version 2>/dev/null || echo unknown))"
  info "pass --force to reinstall"
else
  info "installing yt-transcript from $SCRIPT_DIR"
  if [ "$FORCE" = 1 ] && have yt-transcript; then
    pipx install --force "$SCRIPT_DIR"
  else
    pipx install "$SCRIPT_DIR"
  fi
  ok "yt-transcript installed ($(yt-transcript --version 2>/dev/null || echo '?'))"
fi

echo
info "all set. try:"
printf "  %syt-transcript 'https://youtu.be/dQw4w9WgXcQ'%s\n" "$DIM" "$RESET"
