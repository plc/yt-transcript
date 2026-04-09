# yt-transcript — Session Context

CLI that converts a YouTube URL into a clean text transcript.

## Architecture
- Single Python package `yt_transcript` with `cli.py` as the entrypoint (console script `yt-transcript`).
- Hard deps (runtime, on PATH): `yt-dlp`, `whisper` (openai-whisper). Checked in `preflight()`.
- Work happens in a `tempfile.mkdtemp` dir; cleaned up unless `--keep-temp`.

## Flow
1. `preflight()` verifies `yt-dlp` and `whisper` exist.
2. `resolve_transcript()` dispatches on `--source`:
   - `uploaded` / `auto-captions` / `auto` → `try_captions()` invokes `yt-dlp --skip-download --write-subs/--write-auto-subs --convert-subs vtt`, then `vtt_to_text()` strips markup.
   - `whisper` (or `auto` fallback) → `transcribe_with_whisper()` pulls `bestaudio` as mp3, runs `whisper --output_format txt`.
3. Output goes to `--output` or stdout.

## VTT cleaning notes
YouTube auto-captions emit rolling duplicates (each cue repeats the previous line plus the new word). `vtt_to_text()` handles this with a two-pass filter: drop adjacent equal lines, then drop any line that is a strict prefix of the next.

## Files
- `pyproject.toml` — setuptools, console script
- `yt_transcript/cli.py` — all logic
- `README.md` — user-facing install/usage
- `CHANGELOG.md` — decisions & changes
