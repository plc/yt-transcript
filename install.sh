#!/usr/bin/env bash
# yt-transcript installer
#
# Verifies the required dependencies are present and then installs the
# yt-transcript package itself via pipx.
#
# This script will NOT install dependencies for you — if anything is missing,
# it prints the exact command to install it and exits. Re-run the installer
# after you've installed what was reported.
#
# Required dependencies:
#   - pipx     (to install the package)
#   - yt-dlp   (fetches captions and audio)
#   - ffmpeg   (audio extraction / decoding)
#   - whisper  (local transcription fallback; openai-whisper)
#
# Usage:
#   ./install.sh            # from a local clone — check deps, install yt-transcript
#   ./install.sh --check    # only check deps, do not install anything
#   ./install.sh --force    # reinstall yt-transcript even if already present
#
# Or one-shot from the internet:
#   curl -fsSL https://raw.githubusercontent.com/plc/yt-transcript/main/install.sh | bash
#
# When piped through curl, the script installs from the git URL directly (no
# clone needed).

set -euo pipefail

GIT_URL="https://github.com/plc/yt-transcript.git"

# Detect whether we're running from a local checkout or piped through curl.
# When piped, BASH_SOURCE is typically empty/stdin and there's no pyproject.toml
# to build from — we fall back to installing directly from the git URL.
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  INSTALL_TARGET="$SCRIPT_DIR"
  MODE="local"
else
  SCRIPT_DIR=""
  INSTALL_TARGET="git+$GIT_URL"
  MODE="remote"
fi

CHECK_ONLY=0
FORCE=0
for arg in "${@:-}"; do
  case "$arg" in
    "") ;;
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    -h|--help)
      if [ "$MODE" = local ] && [ -f "$0" ]; then
        awk '/^#!/ {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
      else
        echo "yt-transcript installer — see https://github.com/plc/yt-transcript"
      fi
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

# -------- OS detection (for install-command hints only) --------
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *)      PLATFORM=unknown ;;
esac

install_hint() {
  # $1 = dep name
  case "$1" in
    pipx)
      if [ "$PLATFORM" = macos ]; then echo "brew install pipx && pipx ensurepath"
      elif [ "$PLATFORM" = linux ]; then echo "sudo apt-get install pipx && pipx ensurepath"
      else echo "python3 -m pip install --user pipx && pipx ensurepath"
      fi
      ;;
    yt-dlp)
      if [ "$PLATFORM" = macos ]; then echo "brew install yt-dlp"
      elif [ "$PLATFORM" = linux ]; then echo "sudo apt-get install yt-dlp   # or: pipx install yt-dlp"
      else echo "pipx install yt-dlp"
      fi
      ;;
    ffmpeg)
      if [ "$PLATFORM" = macos ]; then echo "brew install ffmpeg"
      elif [ "$PLATFORM" = linux ]; then echo "sudo apt-get install ffmpeg"
      else echo "install ffmpeg from https://ffmpeg.org/download.html"
      fi
      ;;
    whisper)
      echo "pipx install openai-whisper"
      ;;
    *)
      echo "install $1 manually"
      ;;
  esac
}

# -------- dependency check --------
missing=()
check_dep() {
  local dep="$1"
  if have "$dep"; then
    ok "$dep  ($(command -v "$dep"))"
  else
    err "$dep  (missing)"
    missing+=("$dep")
  fi
}

info "checking dependencies"
check_dep pipx
check_dep yt-dlp
check_dep ffmpeg
check_dep whisper

if [ "${#missing[@]}" -gt 0 ]; then
  echo
  err "${#missing[@]} dependency(s) missing. Install them and re-run this script."
  echo
  for dep in "${missing[@]}"; do
    printf "  %s%s%s:\n    %s%s%s\n" "$BOLD" "$dep" "$RESET" "$DIM" "$(install_hint "$dep")" "$RESET"
  done
  echo
  exit 3
fi

if [ "$CHECK_ONLY" = 1 ]; then
  echo
  ok "all dependencies present"
  exit 0
fi

# -------- install yt-transcript itself --------
echo
if have yt-transcript && [ "$FORCE" != 1 ]; then
  ok "yt-transcript already installed ($(yt-transcript --version 2>/dev/null || echo unknown))"
  info "pass --force to reinstall"
else
  if [ "$MODE" = local ]; then
    info "installing yt-transcript from $SCRIPT_DIR"
  else
    info "installing yt-transcript from $GIT_URL"
  fi
  if [ "$FORCE" = 1 ] && have yt-transcript; then
    pipx install --force "$INSTALL_TARGET"
  else
    pipx install "$INSTALL_TARGET"
  fi
  ok "yt-transcript installed ($(yt-transcript --version 2>/dev/null || echo '?'))"
fi

echo
info "all set. try:"
printf "  %syt-transcript 'https://youtu.be/dQw4w9WgXcQ'%s\n" "$DIM" "$RESET"
