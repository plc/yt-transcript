"""yt-transcript: YouTube URL -> clean text transcript."""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SOURCES = ("auto", "uploaded", "auto-captions", "whisper")


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def preflight() -> None:
    missing = []
    if not shutil.which("yt-dlp"):
        missing.append("yt-dlp (install: `brew install yt-dlp` or `pipx install yt-dlp`)")
    if not shutil.which("whisper"):
        missing.append("whisper (install: `pipx install openai-whisper`)")
    if missing:
        die("missing required dependencies:\n  - " + "\n  - ".join(missing))


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, **kwargs)


def try_captions(url: str, tmp: Path, lang: str, *, uploaded: bool, auto: bool) -> Path | None:
    """Download captions via yt-dlp. Returns path to a .vtt if found."""
    cmd = ["yt-dlp", "--skip-download", "--sub-lang", lang,
           "--sub-format", "vtt", "--convert-subs", "vtt",
           "-o", str(tmp / "%(id)s.%(ext)s")]
    if uploaded:
        cmd.append("--write-subs")
    if auto:
        cmd.append("--write-auto-subs")
    cmd.append(url)

    res = run(cmd)
    if res.returncode != 0:
        return None
    vtts = sorted(glob.glob(str(tmp / "*.vtt")))
    return Path(vtts[0]) if vtts else None


_TIMESTAMP_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->")
_TAG_RE = re.compile(r"<[^>]+>")


def vtt_to_text(path: Path) -> str:
    """Strip VTT markup and collapse the rolling duplicates auto-captions emit."""
    lines_out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
            continue
        if _TIMESTAMP_RE.search(line):
            continue
        if line.isdigit():  # cue number
            continue
        line = _TAG_RE.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if lines_out and lines_out[-1] == line:
            continue
        lines_out.append(line)

    # Second pass: drop lines that are a prefix of the next (rolling captions).
    cleaned: list[str] = []
    for i, line in enumerate(lines_out):
        if i + 1 < len(lines_out) and lines_out[i + 1].startswith(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned) + "\n"


def transcribe_with_whisper(url: str, tmp: Path, model: str) -> str:
    dl = run(["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3",
              "-o", str(tmp / "%(id)s.%(ext)s"), url])
    if dl.returncode != 0:
        die("yt-dlp failed to download audio")
    mp3s = sorted(glob.glob(str(tmp / "*.mp3")))
    if not mp3s:
        die("no audio file produced by yt-dlp")
    audio = mp3s[0]

    print(f"[whisper] transcribing with model={model} ...", file=sys.stderr)
    wh = run(["whisper", audio, "--model", model, "--output_format", "txt",
              "--output_dir", str(tmp)])
    if wh.returncode != 0:
        die("whisper failed")
    txts = sorted(glob.glob(str(tmp / "*.txt")))
    if not txts:
        die("whisper produced no .txt output")
    return Path(txts[0]).read_text(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yt-transcript",
        description="Turn a YouTube video into a clean text transcript.",
    )
    p.add_argument("url", help="YouTube video URL")
    p.add_argument("--source", choices=SOURCES, default="auto",
                   help="transcript source (default: auto — uploaded → auto-captions → whisper)")
    p.add_argument("--lang", default="en", help="caption language code (default: en)")
    p.add_argument("--model", default="small", help="whisper model (default: small)")
    p.add_argument("-o", "--output", help="write transcript to FILE instead of stdout")
    p.add_argument("--keep-temp", action="store_true", help="keep temp dir for debugging")
    return p


def resolve_transcript(url: str, source: str, lang: str, model: str, tmp: Path) -> str:
    if source == "uploaded":
        vtt = try_captions(url, tmp, lang, uploaded=True, auto=False)
        if not vtt:
            die("no uploaded captions found")
        return vtt_to_text(vtt)

    if source == "auto-captions":
        vtt = try_captions(url, tmp, lang, uploaded=False, auto=True)
        if not vtt:
            die("no auto-generated captions found")
        return vtt_to_text(vtt)

    if source == "whisper":
        return transcribe_with_whisper(url, tmp, model)

    # auto: uploaded -> auto-captions -> whisper
    print("[auto] trying uploaded captions ...", file=sys.stderr)
    vtt = try_captions(url, tmp, lang, uploaded=True, auto=False)
    if vtt:
        return vtt_to_text(vtt)
    for f in glob.glob(str(tmp / "*.vtt")):
        os.remove(f)

    print("[auto] trying auto-generated captions ...", file=sys.stderr)
    vtt = try_captions(url, tmp, lang, uploaded=False, auto=True)
    if vtt:
        return vtt_to_text(vtt)

    print("[auto] no captions; falling back to whisper ...", file=sys.stderr)
    return transcribe_with_whisper(url, tmp, model)


def main() -> None:
    args = build_parser().parse_args()
    preflight()

    tmp = Path(tempfile.mkdtemp(prefix="yt-transcript-"))
    try:
        transcript = resolve_transcript(args.url, args.source, args.lang, args.model, tmp)
        if args.output:
            Path(args.output).write_text(transcript, encoding="utf-8")
            print(f"wrote {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(transcript)
        if args.keep_temp:
            print(f"[keep-temp] {tmp}", file=sys.stderr)
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
