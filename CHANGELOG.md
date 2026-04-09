# Changelog

## 0.1.0 — 2026-04-08
- Initial version.
- CLI `yt-transcript` with `--source auto|uploaded|auto-captions|whisper`.
- Captions downloaded via `yt-dlp --skip-download --convert-subs vtt`; parsed in-process (no extra deps).
- Whisper fallback via `yt-dlp -x --audio-format mp3` → `whisper --output_format txt`.
- `yt-dlp` is required at startup; `whisper` is checked lazily — only when the
  chosen source is `whisper`, or when `auto` falls through to it. This lets
  caption-only runs succeed on machines without whisper installed.
- Decision: auto-captions are deduplicated with a prefix-collapse pass to handle YouTube's rolling cues.
