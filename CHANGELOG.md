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

## 0.7.0 — 2026-04-09
- feat: `--sample` and `--sample-seconds N` (default 60) — smoke-test mode that
  processes only the first N seconds of the video end-to-end. Works with
  every `--source`:
  - captions: cues starting at or after N seconds are dropped in-memory.
  - whisper: yt-dlp is invoked with `--download-sections "*0-N"` so only the
    first N seconds of audio are downloaded and decoded; the
    `[whisper-estimate]` line reflects the clamped duration.
- feat: `--sample` without a URL falls back to a built-in default video
  (`https://www.youtube.com/watch?v=3m5qxZm_JqM`). The fastest sanity check
  for a fresh install is now `yt-transcript --sample`.
- feat: JSON output gains `"sample": bool` and `"sample_seconds": int|null`
  so agents can distinguish a clipped transcript from a full one.
- feat: URL positional argument is now optional (required unless `--sample`).
  Missing URL without `--sample` exits 2 with a clear hint.
- internal: `vtt_to_text()` accepts an optional `max_seconds` and parses cue
  start timestamps so captions can be truncated precisely. Used by sample
  mode, but available for any caller.
- docs: README gains a "Sample mode" section, a flags-table entry, and an
  example in the Examples block.

## 0.6.0 — 2026-04-09
- feat: whisper runtime estimate. Before whisper starts, probe the video's
  duration via `yt-dlp --print` (reusing an existing info.json if one is
  already on disk from a prior captions attempt), and print a prominent
  machine-parseable line to stderr **at every verbosity level, including `-q`**:
  ```
  [whisper-estimate] audio=47m23s duration_seconds=2843 model=small \
    est_min_seconds=1421 est_max_seconds=2843 est_range=23m41s-47m23s
  ```
  The key=value format is grep/parse-friendly for agents. Runtime ranges use
  per-model CPU speed multipliers (tiny 5–10x realtime, small 1–2x, large
  0.15–0.3x, etc.).
- feat: `--format json` gains `audio_duration_seconds` and
  `whisper_estimate_seconds: {min, max}` fields (populated only when the
  whisper path runs; `null` for caption sources).
- feat: medium verbosity now streams whisper's per-segment output live instead
  of suppressing it. Eliminates the "is it stuck?" problem on hour-long runs.
  yt-dlp is still suppressed at medium. Silent (`-q`) still hides everything
  except errors and the outcome line. Verbose (`-v`) unchanged.
- docs: new "Long videos" section in README with a per-model CPU speed table
  and recommendations (prefer captions, pick the right model, watch the
  estimate line). JSON section documents the new fields.

## 0.5.2 — 2026-04-09
- feat: `install.sh` detects when it's being piped through curl (no local
  `pyproject.toml` next to it) and installs from the git URL instead of a
  local path. Enables one-shot install:
  `curl -fsSL https://raw.githubusercontent.com/plc/yt-transcript/main/install.sh | bash`
- docs: README shows three install paths — direct `pipx install git+...`,
  `curl | bash`, and local clone + `./install.sh`.

## 0.5.1 — 2026-04-09
- change: `install.sh` no longer installs system dependencies. It checks for
  `pipx`, `yt-dlp`, `ffmpeg`, and `whisper`; if any are missing it prints the
  exact install command (platform-aware — brew on macOS, apt on Linux) and
  exits 3. The user installs what's missing and re-runs. The script still
  installs the `yt-transcript` package itself via pipx once all deps are
  present. `--check` / `--force` flags preserved.
- fix: `install.sh --help` no longer leaks the `set -euo pipefail` line.

## 0.5.0 — 2026-04-09
- feat: `install.sh` bundled installer. Idempotent, detects macOS vs Linux,
  uses Homebrew or apt for `yt-dlp`/`ffmpeg`, pipx for `openai-whisper` and the
  `yt-transcript` package itself. Supports `--check` (report only, no install)
  and `--force` (reinstall yt-transcript). Tries to auto-install pipx if missing.
- docs: README install section documents both the scripted and manual paths.

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
