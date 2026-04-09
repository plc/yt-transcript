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

## 0.4.0 — 2026-04-09
- feat: `--version` flag.
- feat: `--format {txt,json}` (default `txt`). JSON mode emits a single object
  containing the transcript plus structured metadata: `source` (which one
  actually produced the transcript — useful for `--source auto`), `language`,
  `model`, `video_id`, `title`, `duration`, `uploader`, `webpage_url`, and
  `chars`. Metadata is extracted from yt-dlp's own `--write-info-json` sidecar,
  so it's free — no extra network calls.
- internal: `resolve_transcript()` now returns a `Result` dataclass instead of a
  bare string, centralizing the metadata plumbing.
- docs: README documents the JSON schema and adds a version example.

## 0.3.0 — 2026-04-09
- feat: up-front URL validation. Rejects empty input, non-YouTube domains, and
  backslash-mangled URLs (common zsh `url-quote-magic` mishap) with specific
  messages before spawning yt-dlp. Exit code 2.
- feat: `ffmpeg` added to preflight for `auto` and `whisper` sources (checked
  lazily — captions-only modes still don't need it). Exit code 3 for any
  missing dependency, with an install hint.
- feat: structured exit codes — `0` ok, `2` usage, `3` missing dep, `4` yt-dlp
  download failure, `5` no captions found, `6` whisper failure, `7` output I/O
  error, `130` Ctrl-C. Documented in README.
- feat: specific, actionable error messages for download failures (lists likely
  causes: private video, region block, stale yt-dlp), caption misses (suggests
  alternative sources), whisper failures (reminds of valid model names), and
  output write failures (surfaces the OSError).
- feat: graceful `KeyboardInterrupt` handling — prints `interrupted` and exits
  `130` instead of dumping a traceback.
- docs: comprehensive README rewrite with a flags table, examples per mode,
  verbosity level explanations, exit code table, and troubleshooting section
  covering the zsh paste issue, stale yt-dlp, missing captions, and slow whisper.

## 0.2.0 — 2026-04-08
- feat: `--verbosity {silent,medium,verbose}` (default `medium`) plus `-q`/`-v`
  shortcuts. Medium shows only our step markers; silent suppresses everything
  except errors and the final outcome line; verbose streams yt-dlp and whisper
  output as before. When not verbose, yt-dlp runs with `--quiet --no-warnings`
  and whisper with `--verbose False`; on failure, the last 20 lines of their
  captured output are printed so debugging still works.
