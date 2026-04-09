# yt-transcript

A small CLI that turns a YouTube URL into a clean text transcript.

It prefers real captions (fast, free, accurate) and falls back to local
[OpenAI Whisper](https://github.com/openai/whisper) only when none are
available. You can also force a specific source.

- **`auto`** (default) — uploaded captions → YouTube auto-captions → Whisper
- **`uploaded`** — human-uploaded subtitles only
- **`auto-captions`** — YouTube's auto-generated captions only
- **`whisper`** — skip captions, download audio, transcribe locally

## Install

Assuming dependencies (`pipx`, `yt-dlp`, `ffmpeg`, `whisper`) are already installed, the fastest path is a one-shot pipx install:

```sh
pipx install git+https://github.com/plc/yt-transcript.git
```

Or run the bundled installer via curl — it checks your dependencies first, tells you exactly what's missing (with the install command), and only proceeds once everything is in place:

```sh
curl -fsSL https://raw.githubusercontent.com/plc/yt-transcript/main/install.sh | bash
```

Or from a local clone:

```sh
git clone https://github.com/plc/yt-transcript.git
cd yt-transcript
./install.sh
```

The installer checks for `pipx`, `yt-dlp`, `ffmpeg`, and `whisper`. If any are
missing it prints the exact install command for your platform (brew on macOS,
apt on Linux) and exits `3` — install what it reports and re-run. Once all deps
are present it installs the `yt-transcript` command into an isolated pipx venv.

- `./install.sh --check` — check deps only, don't install anything
- `./install.sh --force` — reinstall `yt-transcript` even if already present

The same flags work through curl:
```sh
curl -fsSL https://raw.githubusercontent.com/plc/yt-transcript/main/install.sh | bash -s -- --check
```

Quick one-time test without installing:

```sh
python3 yt_transcript/cli.py 'https://youtu.be/dQw4w9WgXcQ'
```

See [Requirements](#requirements) for the full dependency matrix and manual
install commands.

## Requirements

All three tools must be on your `PATH`:

| Tool          | Why it's needed                                                   | Install                                      |
|---------------|-------------------------------------------------------------------|----------------------------------------------|
| `yt-dlp`      | fetches captions and audio                                        | `brew install yt-dlp`                        |
| `ffmpeg`      | audio extraction for yt-dlp; audio decoding for whisper           | `brew install ffmpeg`                        |
| `whisper`     | local transcription fallback (only needed when captions miss)     | `pipx install openai-whisper`                |

Python 3.9+.

`ffmpeg` and `whisper` are only strictly required if you'll actually
transcribe. The CLI checks them lazily based on `--source`:

- `--source uploaded` / `auto-captions` — needs only `yt-dlp`
- `--source auto` — needs `yt-dlp` + `ffmpeg` (whisper checked only if both caption passes fail)
- `--source whisper` — needs all three up front

## Manual install

If you'd rather not use the installer script:

```sh
brew install yt-dlp ffmpeg       # or: sudo apt-get install yt-dlp ffmpeg
pipx install openai-whisper
pipx install .                   # from the repo root
```

## Usage

```
yt-transcript URL [--source auto|uploaded|auto-captions|whisper]
                  [--lang en] [--model small]
                  [-o FILE] [--keep-temp]
                  [-q | -v | --verbosity silent|medium|verbose]
```

### Flags

| Flag                   | Default   | Description                                                                 |
|------------------------|-----------|-----------------------------------------------------------------------------|
| `URL`                  | —         | YouTube video URL (`https://www.youtube.com/watch?v=...` or `https://youtu.be/...`) |
| `--source`             | `auto`    | Where to get the transcript from (see modes above)                          |
| `--lang`               | `en`      | Caption language code (ISO 639-1)                                           |
| `--model`              | `small`   | Whisper model: `tiny`, `base`, `small`, `medium`, `large`                   |
| `--format`             | `txt`     | Output format: `txt` (plain transcript) or `json` (structured, see below)   |
| `-o`, `--output FILE`  | stdout    | Write output to FILE instead of stdout                                      |
| `--version`            | —         | Print version and exit                                                      |
| `--sample [SECONDS]`   | off       | Sample mode: only process the first SECONDS of the video (default 60 when no number given). Smoke-tests the full pipeline end to end. If no URL is given, a built-in default is used. |
| `--keep-temp`          | off       | Don't delete the working directory (for debugging)                          |
| `-q`, `--quiet`        | —         | Silent: only errors and the final outcome line                              |
| `-v`, `--verbose`      | —         | Verbose: stream all yt-dlp / whisper output                                 |

Default verbosity (no flag) is "medium": our own step markers plus whisper's
live per-segment progress. `-q` and `-v` are mutually exclusive.

### Examples

```sh
# Smoke-test the whole pipeline (first 60s only, built-in sample URL).
yt-transcript --sample

# Same, but your own URL.
yt-transcript --sample 'https://youtu.be/...'

# Longer clip.
yt-transcript --sample 120 'https://youtu.be/...'

# Print version.
yt-transcript --version

# Simplest: print transcript to stdout.
yt-transcript 'https://youtu.be/dQw4w9WgXcQ'

# Write to a file, silently.
yt-transcript -q -o out.txt 'https://youtu.be/dQw4w9WgXcQ'

# Only use human-uploaded Spanish captions; fail if absent.
yt-transcript --source uploaded --lang es 'https://youtu.be/...'

# Skip captions and always transcribe locally with the medium model.
yt-transcript --source whisper --model medium 'https://youtu.be/...'

# See every yt-dlp and whisper line for debugging.
yt-transcript -v 'https://youtu.be/...'

# Structured output for scripts and agents.
yt-transcript --format json -q 'https://youtu.be/...'
```

### JSON output (for agents and scripts)

`--format json` emits a single JSON object on stdout. Combine with `-q` to
keep stderr clean. Shape:

```json
{
  "transcript": "...",
  "source": "uploaded",           // uploaded | auto-captions | whisper
  "language": "en",               // for caption sources; null for whisper
  "model": null,                  // whisper model if source == whisper; else null
  "video_id": "dQw4w9WgXcQ",
  "title": "...",
  "duration": 213,                // seconds
  "uploader": "...",
  "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "chars": 4823,
  "audio_duration_seconds": null,       // set only when source == whisper
  "whisper_estimate_seconds": null,     // set only when source == whisper
  "sample": false,                      // true when --sample is in effect
  "sample_seconds": null                // clip length when sample is true
}
```

When the whisper path is used, the last two fields are populated:

```json
{
  "source": "whisper",
  "model": "small",
  "audio_duration_seconds": 2843.0,
  "whisper_estimate_seconds": { "min": 1421, "max": 2843 }
}
```

Metadata fields come from yt-dlp's `--write-info-json` sidecar; any field that
yt-dlp didn't populate will be `null`. `source` is always the one that actually
produced the transcript — so in `--source auto` an agent can see whether it got
uploaded captions, auto-captions, or fell back to whisper.

### Sample mode (smoke test)

`--sample` truncates the run to the first N seconds of video so you can verify
the whole pipeline end-to-end in under a minute without waiting for a full
transcription. It works with every `--source`:

- **Captions sources** — the VTT is parsed as usual, then cues starting at or
  after `sample_seconds` are dropped in-memory. Essentially free.
- **Whisper** — yt-dlp is called with `--download-sections "*0-N"`, so only
  the first N seconds of audio are actually downloaded and decoded. The
  `[whisper-estimate]` line uses the clamped duration, not the full video.

If you don't provide a URL, sample mode falls back to a built-in default video
(`https://www.youtube.com/watch?v=3m5qxZm_JqM`). So the fastest possible
sanity check for a fresh install is:

```sh
yt-transcript --sample
```

In `--format json`, sample mode sets `"sample": true` and
`"sample_seconds": 60` so agents can tell the transcript is clipped, not the
whole video.

### Long videos and the whisper estimate

Before whisper runs, yt-transcript probes the video duration (a fast metadata-only
yt-dlp call) and prints a machine-parseable estimate line to stderr — always,
at every verbosity level including `-q`. This is the single most important
signal for agents running whisper: it tells you up front whether you're waiting
minutes or hours.

```
[whisper-estimate] audio=47m23s duration_seconds=2843 model=small est_min_seconds=1421 est_max_seconds=2843 est_range=23m41s-47m23s
```

The format is `key=value` pairs separated by spaces so you can `grep` and parse
it without a regex library. The same numbers appear in `--format json` as
`audio_duration_seconds` and `whisper_estimate_seconds.{min,max}`.

See the [Long videos](#long-videos) section below for model speed guidance.

### Verbosity levels

- **silent** (`-q`) — only errors and a single `wrote FILE (N chars)` outcome line. yt-dlp runs with `--quiet --no-warnings` and whisper with `--verbose False`. On any failure, the last 20 lines of their captured output are still printed so you can diagnose.
- **medium** (default, no flag) — step markers plus whisper's live per-segment output, e.g.:
  ```
  [auto] trying uploaded captions ...
  [auto] trying auto-generated captions ...
  [auto] no captions; falling back to whisper ...
  [yt-dlp] downloading audio ...
  [whisper] transcribing with model=small ... (this may take a while)
  wrote out.txt (4823 chars)
  ```
- **verbose** (`-v`) — streams yt-dlp's progress in addition to whisper's.

## Long videos

If your video has captions, length doesn't matter — the captions path
downloads a single small VTT file and cleans it in microseconds regardless of
how long the video is. A 4-hour podcast is no different from a 4-minute clip.

The whisper path is where length matters. On a modern Mac CPU, openai-whisper
processes audio at very different speeds depending on the model:

| model    | speed (CPU)       | 1h audio   | notes                                    |
|----------|-------------------|------------|------------------------------------------|
| `tiny`   | ~5–10× realtime   | ~6–12 min  | fast draft quality                       |
| `base`   | ~3–5× realtime    | ~12–20 min | slightly better than tiny                |
| `small`  | ~1–2× realtime    | ~30–60 min | **default** — decent quality             |
| `medium` | ~0.4–0.8× realtime| ~2 h       | notably better, notably slower           |
| `large`  | ~0.15–0.3× realtime| ~4–7 h    | best accuracy, very slow on CPU          |

**Recommendations for long videos:**

1. **Always try captions first.** The default `--source auto` does this — it
   only falls back to whisper when both caption passes fail. Running
   `--source auto` on an hour-long interview that has human captions costs you
   roughly a single yt-dlp roundtrip, not an hour of CPU.
2. **If you must use whisper, pick the right model for the job.** For
   searchable text / rough understanding, `--model tiny` or `--model base`
   usually suffices and is 5–10× faster than the default. Reserve `small`,
   `medium`, and `large` for cases where you genuinely need the accuracy.
3. **Watch the estimate line.** Before whisper starts, yt-transcript prints a
   `[whisper-estimate]` line to stderr (see [JSON output](#json-output-for-agents-and-scripts)
   above) telling you the audio length and expected runtime range. If it says
   `est_range=4h-7h` and you didn't expect that, hit Ctrl-C and rerun with
   `--model tiny`.
4. **At `medium` verbosity (the default) whisper streams per-segment output.**
   You'll see lines like `[00:05:30.000 --> 00:05:34.200]  ... text ...` tick
   by as it works, so you can tell it's making progress on long runs.
   `-q` suppresses this; `-v` is identical to medium for whisper.

There's no hard length limit — whisper chunks audio internally into
30-second windows, so multi-hour videos work fine as long as you're patient.

## How it works

1. **URL validation.** Obviously broken input (empty, backslash-mangled, non-YouTube) is rejected before we spawn anything.
2. **Preflight.** Verifies the dependencies you'll actually need.
3. **Temp workspace.** All intermediate files go to a temp dir which is removed on exit (unless `--keep-temp`).
4. **Captions path.** Runs `yt-dlp --skip-download --write-subs/--write-auto-subs --convert-subs vtt` and, if a `.vtt` lands in the temp dir, runs it through a small in-process cleaner that strips timestamps, cue numbers, and markup. YouTube's auto-captions emit rolling duplicates (each cue repeats the previous line plus one new word); a two-pass prefix-collapse filter turns that back into clean text. No extra Python dependency.
5. **Whisper path.** Runs `yt-dlp -f bestaudio -x --audio-format mp3` to pull the audio, then `whisper <file>.mp3 --model <model> --output_format txt`, and reads the resulting `.txt`.

## Error handling

The CLI validates before it acts and reports specific, actionable errors instead of generic crashes. Every failure mode below gets a clear message and a distinct exit code.

| Exit | Meaning                 | When you'll see it                                             |
|------|-------------------------|----------------------------------------------------------------|
| `0`  | success                 | transcript was produced                                        |
| `2`  | bad usage               | invalid or empty URL; shell-mangled URL (`\?` / `\=`); not a YouTube domain |
| `3`  | missing dependency      | `yt-dlp`, `ffmpeg`, or `whisper` not on PATH (checked lazily by mode) |
| `4`  | download failed         | yt-dlp failed — private video, region block, network, stale yt-dlp |
| `5`  | no captions found       | `--source uploaded` / `auto-captions` but the video has none in that lang |
| `6`  | whisper failed          | bad model name, decoding error, OOM                            |
| `7`  | output I/O failed       | couldn't write `-o FILE` (permission, disk, directory missing) |
| `130`| interrupted             | Ctrl-C                                                         |

When yt-dlp or whisper fails at `silent`/`medium` verbosity, the last 20 lines of their captured output are printed to stderr alongside the error — you don't need to re-run with `-v` to see what went wrong.

## Troubleshooting

**"URL contains backslash-escaped characters"**
Your shell (zsh `url-quote-magic`) mangled a pasted URL into `watch\?v\=...`. Fix: wrap the paste in single quotes, or use the short form `https://youtu.be/<ID>` which has no `?` or `=` for the shell to escape.

**"yt-dlp failed to download audio. ... outdated yt-dlp"**
YouTube changes its streaming endpoints often. Run `brew upgrade yt-dlp` (or `pipx upgrade yt-dlp`) and try again.

**"no uploaded captions found for lang='en'"**
The video genuinely doesn't have human-uploaded English subs. Try `--source auto-captions`, `--source whisper`, or a different `--lang`.

**Whisper is slow**
First run downloads the model weights (hundreds of MB for `small`, several GB for `large`). Subsequent runs reuse the cache. Use `--model tiny` or `--model base` for quick drafts; `small` (default) is a reasonable balance; `medium`/`large` are better but much slower on CPU. On CPU you'll see `FP16 is not supported on CPU; using FP32 instead` — harmless.

**I want to see exactly what's happening**
Use `-v` (verbose) and/or `--keep-temp` to keep the working directory around after exit.

## Project layout

```
yt_transcript/
  __init__.py
  cli.py            # all logic
pyproject.toml      # setuptools, console script
README.md           # this file
CHANGELOG.md        # decisions & changes
CLAUDE.md           # session context for future Claude sessions
```

## License

MIT-style; do what you want.
