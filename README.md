# yt-transcript

Turn a YouTube video into a clean text transcript. Prefers captions (fast, free) and falls back to local [Whisper](https://github.com/openai/whisper) when none are available.

## Requirements

Both must be on your `PATH`:

- `yt-dlp` — `brew install yt-dlp` or `pipx install yt-dlp`
- `whisper` — `pipx install openai-whisper` (also needs `ffmpeg`: `brew install ffmpeg`)

## Install

```sh
pipx install .
```

## Usage

```sh
yt-transcript <url> [--source auto|uploaded|auto-captions|whisper]
              [--lang en] [--model small] [-o FILE] [--keep-temp]
```

### Sources

- `auto` (default) — uploaded captions → auto-captions → whisper
- `uploaded` — human-uploaded subtitles only
- `auto-captions` — YouTube auto-generated captions only
- `whisper` — skip captions, download audio, transcribe locally

### Examples

```sh
yt-transcript https://youtu.be/VIDEO_ID
yt-transcript https://youtu.be/VIDEO_ID --source whisper --model medium
yt-transcript https://youtu.be/VIDEO_ID --source uploaded --lang es -o out.txt
```
