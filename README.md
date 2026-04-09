# yt-transcript

A small CLI that turns a YouTube URL into a clean text transcript.

It prefers real captions (fast, free, accurate) and falls back to local
[OpenAI Whisper](https://github.com/openai/whisper) only when none are
available. You can also force a specific source.

- **`auto`** (default) — uploaded captions → YouTube auto-captions → Whisper
- **`uploaded`** — human-uploaded subtitles only
- **`auto-captions`** — YouTube's auto-generated captions only
- **`whisper`** — skip captions, download audio, transcribe locally

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

## Install

```sh
git clone https://github.com/plc/yt_transcript.git
cd yt_transcript
pipx install .
```

Now you have a `yt-transcript` command on your PATH.

Or, without installing, run the script directly:

```sh
python3 yt_transcript/cli.py ...
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
| `--keep-temp`          | off       | Don't delete the working directory (for debugging)                          |
| `-q`, `--quiet`        | —         | Silent: only errors and the final outcome line                              |
| `-v`, `--verbose`      | —         | Verbose: stream all yt-dlp / whisper output                                 |
| `--verbosity LEVEL`    | `medium`  | `silent` \| `medium` \| `verbose`                                            |

### Examples

```sh
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
  "chars": 4823
}
```

Metadata fields come from yt-dlp's `--write-info-json` sidecar; any field that
yt-dlp didn't populate will be `null`. `source` is always the one that actually
produced the transcript — so in `--source auto` an agent can see whether it got
uploaded captions, auto-captions, or fell back to whisper.

### Verbosity levels

- **`silent`** (`-q`) — only errors and a single `wrote FILE (N chars)` outcome line. yt-dlp runs with `--quiet --no-warnings` and whisper with `--verbose False`. On any failure, the last 20 lines of their captured output are still printed so you can diagnose.
- **`medium`** (default) — step markers only, e.g.:
  ```
  [auto] trying uploaded captions ...
  [auto] trying auto-generated captions ...
  [auto] no captions; falling back to whisper ...
  [yt-dlp] downloading audio ...
  [whisper] transcribing with model=small ... (this may take a while)
  wrote out.txt (4823 chars)
  ```
- **`verbose`** (`-v`) — streams yt-dlp's progress and whisper's live transcript to your terminal.

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
