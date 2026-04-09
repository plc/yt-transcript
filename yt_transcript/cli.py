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
VERBOSITIES = ("silent", "medium", "verbose")

# Verbosity levels as ints for easy comparison.
V_SILENT = 0
V_MEDIUM = 1
V_VERBOSE = 2
_V_MAP = {"silent": V_SILENT, "medium": V_MEDIUM, "verbose": V_VERBOSE}


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def require(tool: str, hint: str) -> None:
    if not shutil.which(tool):
        die(f"missing required dependency: {tool} ({hint})")


def preflight(source: str) -> None:
    require("yt-dlp", "install: `brew install yt-dlp` or `pipx install yt-dlp`")
    if source == "whisper":
        require("whisper", "install: `pipx install openai-whisper`")


class Logger:
    """Minimal leveled logger. Writes status messages to stderr."""

    def __init__(self, level: int):
        self.level = level

    def info(self, msg: str) -> None:
        """Shown at medium and verbose."""
        if self.level >= V_MEDIUM:
            print(msg, file=sys.stderr)

    def debug(self, msg: str) -> None:
        """Shown only at verbose."""
        if self.level >= V_VERBOSE:
            print(msg, file=sys.stderr)

    def subprocess_kwargs(self) -> dict:
        """Kwargs for subprocess.run to forward or suppress child output.

        - verbose: inherit stdout/stderr (live output from yt-dlp/whisper).
        - medium/silent: swallow stdout+stderr; we'll surface a snippet on failure.
        """
        if self.level >= V_VERBOSE:
            return {}
        return {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True}


def run(cmd: list[str], log: Logger) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, **log.subprocess_kwargs())


def _tail(s: str | None, n: int = 20) -> str:
    if not s:
        return ""
    lines = s.rstrip().splitlines()
    return "\n".join(lines[-n:])


def try_captions(
    url: str, tmp: Path, lang: str, log: Logger, *, uploaded: bool, auto: bool
) -> Path | None:
    """Download captions via yt-dlp. Returns path to a .vtt if found."""
    cmd = ["yt-dlp", "--skip-download", "--sub-lang", lang,
           "--sub-format", "vtt", "--convert-subs", "vtt",
           "-o", str(tmp / "%(id)s.%(ext)s")]
    if log.level < V_VERBOSE:
        cmd += ["--quiet", "--no-warnings"]
    if uploaded:
        cmd.append("--write-subs")
    if auto:
        cmd.append("--write-auto-subs")
    cmd.append(url)

    res = run(cmd, log)
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


def transcribe_with_whisper(url: str, tmp: Path, model: str, log: Logger) -> str:
    require("whisper", "install: `pipx install openai-whisper`")

    log.info("[yt-dlp] downloading audio ...")
    dl_cmd = ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3",
              "-o", str(tmp / "%(id)s.%(ext)s"), url]
    if log.level < V_VERBOSE:
        dl_cmd += ["--quiet", "--no-warnings"]
    dl = run(dl_cmd, log)
    if dl.returncode != 0:
        if log.level < V_VERBOSE and dl.stdout:
            print(_tail(dl.stdout), file=sys.stderr)
        die("yt-dlp failed to download audio")
    mp3s = sorted(glob.glob(str(tmp / "*.mp3")))
    if not mp3s:
        die("no audio file produced by yt-dlp")
    audio = mp3s[0]

    log.info(f"[whisper] transcribing with model={model} ...")
    wh_cmd = ["whisper", audio, "--model", model, "--output_format", "txt",
              "--output_dir", str(tmp)]
    if log.level < V_VERBOSE:
        # Whisper prints its progressive transcript when --verbose True (default).
        wh_cmd += ["--verbose", "False"]
    wh = run(wh_cmd, log)
    if wh.returncode != 0:
        if log.level < V_VERBOSE and wh.stdout:
            print(_tail(wh.stdout), file=sys.stderr)
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

    vg = p.add_mutually_exclusive_group()
    vg.add_argument("--verbosity", choices=VERBOSITIES, default="medium",
                    help="output verbosity (default: medium)")
    vg.add_argument("-q", "--quiet", dest="verbosity", action="store_const",
                    const="silent", help="silent: only errors and the final outcome")
    vg.add_argument("-v", "--verbose", dest="verbosity", action="store_const",
                    const="verbose", help="verbose: stream all yt-dlp and whisper output")
    return p


def resolve_transcript(
    url: str, source: str, lang: str, model: str, tmp: Path, log: Logger
) -> str:
    if source == "uploaded":
        log.info("[captions] fetching uploaded captions ...")
        vtt = try_captions(url, tmp, lang, log, uploaded=True, auto=False)
        if not vtt:
            die("no uploaded captions found")
        return vtt_to_text(vtt)

    if source == "auto-captions":
        log.info("[captions] fetching auto-generated captions ...")
        vtt = try_captions(url, tmp, lang, log, uploaded=False, auto=True)
        if not vtt:
            die("no auto-generated captions found")
        return vtt_to_text(vtt)

    if source == "whisper":
        return transcribe_with_whisper(url, tmp, model, log)

    # auto: uploaded -> auto-captions -> whisper
    log.info("[auto] trying uploaded captions ...")
    vtt = try_captions(url, tmp, lang, log, uploaded=True, auto=False)
    if vtt:
        return vtt_to_text(vtt)
    for f in glob.glob(str(tmp / "*.vtt")):
        os.remove(f)

    log.info("[auto] trying auto-generated captions ...")
    vtt = try_captions(url, tmp, lang, log, uploaded=False, auto=True)
    if vtt:
        return vtt_to_text(vtt)

    log.info("[auto] no captions; falling back to whisper ...")
    return transcribe_with_whisper(url, tmp, model, log)


def main() -> None:
    args = build_parser().parse_args()
    log = Logger(_V_MAP[args.verbosity])
    preflight(args.source)

    tmp = Path(tempfile.mkdtemp(prefix="yt-transcript-"))
    try:
        transcript = resolve_transcript(
            args.url, args.source, args.lang, args.model, tmp, log
        )
        if args.output:
            Path(args.output).write_text(transcript, encoding="utf-8")
            # Outcome line: shown at every level (including silent).
            print(f"wrote {args.output} ({len(transcript)} chars)", file=sys.stderr)
        else:
            sys.stdout.write(transcript)
        if args.keep_temp:
            print(f"[keep-temp] {tmp}", file=sys.stderr)
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
