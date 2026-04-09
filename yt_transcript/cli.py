"""yt-transcript: YouTube URL -> clean text transcript."""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__


SOURCES = ("auto", "uploaded", "auto-captions", "whisper")
VERBOSITIES = ("silent", "medium", "verbose")
FORMATS = ("txt", "json")

# Default video used when --sample is passed without a URL. A short, always-
# available public video is best here; this is just a smoke-test target.
DEFAULT_SAMPLE_URL = "https://www.youtube.com/watch?v=3m5qxZm_JqM"
DEFAULT_SAMPLE_SECONDS = 60

# Verbosity levels as ints for easy comparison.
V_SILENT = 0
V_MEDIUM = 1
V_VERBOSE = 2
_V_MAP = {"silent": V_SILENT, "medium": V_MEDIUM, "verbose": V_VERBOSE}

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 2        # invalid arguments / bad URL
EXIT_MISSING_DEP = 3  # required binary not on PATH
EXIT_DOWNLOAD = 4     # yt-dlp failure (network, private video, etc.)
EXIT_NO_CAPTIONS = 5  # requested caption source yielded nothing
EXIT_WHISPER = 6      # whisper failed to transcribe
EXIT_IO = 7           # output file write failed
EXIT_INTERRUPT = 130  # Ctrl-C


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def require(tool: str, hint: str) -> None:
    if not shutil.which(tool):
        die(f"missing required dependency: {tool!r} not found on PATH.\n"
            f"       {hint}", code=EXIT_MISSING_DEP)


def preflight(source: str) -> None:
    require("yt-dlp", "install: `brew install yt-dlp` or `pipx install yt-dlp`")
    # ffmpeg is used by yt-dlp for audio extraction and by whisper for decoding.
    # Only strictly needed when we'll be transcribing, but auto may fall through
    # to whisper, so we check it up front for anything except pure-captions modes.
    if source in ("auto", "whisper"):
        require("ffmpeg",
                "install: `brew install ffmpeg` (required for audio extraction and whisper)")
    if source == "whisper":
        require("whisper", "install: `pipx install openai-whisper`")


_URL_RE = re.compile(
    r"^https?://("
    r"(?:www\.|m\.|music\.)?youtube\.com/"
    r"|youtu\.be/"
    r")",
    re.IGNORECASE,
)


def validate_url(url: str) -> None:
    """Reject obviously bad input before handing it to yt-dlp."""
    if not url or not url.strip():
        die("URL is empty", code=EXIT_USAGE)
    u = url.strip()
    if "\\?" in u or "\\=" in u:
        die("URL contains backslash-escaped characters (\\? or \\=). "
            "Your shell likely mangled the paste. "
            "Wrap the URL in single quotes, or use the short form https://youtu.be/<ID>.",
            code=EXIT_USAGE)
    if not _URL_RE.match(u):
        die(f"not a recognized YouTube URL: {u!r}\n"
            f"       expected https://www.youtube.com/watch?v=<ID> or https://youtu.be/<ID>",
            code=EXIT_USAGE)


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


@dataclass
class Result:
    """Everything an agent might want to know about a run."""
    transcript: str
    source: str                # which source actually produced the transcript
    language: str | None = None  # caption language (captions sources) or detected (whisper)
    model: str | None = None   # whisper model, if used
    video_id: str | None = None
    title: str | None = None
    duration: float | None = None
    uploader: str | None = None
    webpage_url: str | None = None
    # Populated only for the whisper path. Lets agents gauge runtime up front.
    audio_duration_seconds: float | None = None
    whisper_estimate_seconds: dict | None = None  # {"min": int, "max": int}


# Rough CPU-speed multipliers for each whisper model, as multiples of realtime
# (range is min..max). Used purely for pre-run estimates logged to stderr and
# reported in JSON output — NOT a hard limit.
_WHISPER_SPEED = {
    "tiny":   (5.0, 10.0),
    "base":   (3.0, 5.0),
    "small":  (1.0, 2.0),
    "medium": (0.4, 0.8),
    "large":  (0.15, 0.3),
    "large-v2": (0.15, 0.3),
    "large-v3": (0.15, 0.3),
}


def _estimate_whisper_seconds(duration_s: float, model: str) -> dict | None:
    """Return {"min": int, "max": int} for how long whisper will likely take."""
    lo_hi = _WHISPER_SPEED.get(model)
    if not lo_hi:
        return None
    lo_speed, hi_speed = lo_hi
    # faster speed = shorter runtime
    return {
        "min": int(round(duration_s / hi_speed)),
        "max": int(round(duration_s / lo_speed)),
    }


def _fmt_hms(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def probe_duration(url: str, log: Logger) -> float | None:
    """Ask yt-dlp for the video duration without downloading. Fast."""
    cmd = ["yt-dlp", "--skip-download", "--quiet", "--no-warnings",
           "--print", "%(duration)s", url]
    try:
        res = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    if res.returncode != 0:
        return None
    out = (res.stdout or "").strip().splitlines()
    if not out:
        return None
    try:
        return float(out[-1])
    except ValueError:
        return None


def _read_info_json(tmp: Path) -> dict:
    """Return the first *.info.json yt-dlp wrote, or {}."""
    files = sorted(glob.glob(str(tmp / "*.info.json")))
    if not files:
        return {}
    try:
        return json.loads(Path(files[0]).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def _meta_from_info(info: dict) -> dict:
    """Extract just the fields we expose."""
    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "webpage_url": info.get("webpage_url"),
    }


def try_captions(
    url: str, tmp: Path, lang: str, log: Logger, *, uploaded: bool, auto: bool
) -> Path | None:
    """Download captions via yt-dlp. Returns path to a .vtt if found.

    Also writes a sidecar *.info.json which callers can read for metadata.
    """
    cmd = ["yt-dlp", "--skip-download", "--sub-lang", lang,
           "--sub-format", "vtt", "--convert-subs", "vtt",
           "--write-info-json",
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
_CUE_START_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->")
_TAG_RE = re.compile(r"<[^>]+>")


def vtt_to_text(path: Path, max_seconds: float | None = None) -> str:
    """Strip VTT markup and collapse the rolling duplicates auto-captions emit.

    If max_seconds is set, cues starting at or after that time are dropped.
    This is used by sample mode to truncate captions to the first N seconds.
    """
    lines_out: list[str] = []
    current_start: float = 0.0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
            continue
        m = _CUE_START_RE.match(line)
        if m:
            h, mi, s, ms = (int(x) for x in m.groups())
            current_start = h * 3600 + mi * 60 + s + ms / 1000.0
            continue
        if _TIMESTAMP_RE.search(line):
            # A timestamp line that didn't match the start-of-cue anchor — drop.
            continue
        if line.isdigit():  # cue number
            continue
        if max_seconds is not None and current_start >= max_seconds:
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


def transcribe_with_whisper(
    url: str, tmp: Path, model: str, log: Logger,
    sample_seconds: int | None = None,
) -> tuple[str, float | None, dict | None]:
    """Run the whisper path. Returns (transcript_text, duration_s, estimate_dict).

    If sample_seconds is set, only the first N seconds of audio are downloaded
    (via yt-dlp --download-sections) and the estimate reflects that shorter
    clip — not the full video length.

    Before downloading audio, this function probes the video's duration and
    prints a prominent estimate line to stderr so users (and agents scraping
    stderr) know roughly how long the run will take. The estimate is also
    returned to the caller for inclusion in the JSON output.
    """
    require("whisper", "install: `pipx install openai-whisper`")

    # --- Duration probe + estimate (shown BEFORE the slow work starts) -------
    # Reuse metadata from a prior yt-dlp call (e.g. captions attempts in auto
    # mode) if available — saves a roundtrip. Otherwise probe explicitly.
    full_duration_s: float | None = None
    info = _read_info_json(tmp)
    if info.get("duration") is not None:
        try:
            full_duration_s = float(info["duration"])
        except (TypeError, ValueError):
            full_duration_s = None
    if full_duration_s is None:
        full_duration_s = probe_duration(url, log)

    # Effective duration whisper will actually process (clamped in sample mode).
    if sample_seconds is not None and full_duration_s is not None:
        duration_s: float | None = min(full_duration_s, float(sample_seconds))
    elif sample_seconds is not None:
        duration_s = float(sample_seconds)
    else:
        duration_s = full_duration_s

    estimate = _estimate_whisper_seconds(duration_s, model) if duration_s else None

    # Always surface this, even in --quiet mode. It's the single most important
    # piece of information for long videos, and agents parsing stderr need it.
    # Machine-friendly key=value form:
    if duration_s is not None:
        if estimate is not None:
            print(
                f"[whisper-estimate] audio={_fmt_hms(duration_s)} "
                f"duration_seconds={int(round(duration_s))} "
                f"model={model} "
                f"est_min_seconds={estimate['min']} est_max_seconds={estimate['max']} "
                f"est_range={_fmt_hms(estimate['min'])}-{_fmt_hms(estimate['max'])}",
                file=sys.stderr,
            )
        else:
            print(
                f"[whisper-estimate] audio={_fmt_hms(duration_s)} "
                f"duration_seconds={int(round(duration_s))} "
                f"model={model} est=unknown",
                file=sys.stderr,
            )
    else:
        print(
            f"[whisper-estimate] duration=unknown model={model}",
            file=sys.stderr,
        )

    # --- Audio download ------------------------------------------------------
    if sample_seconds is not None:
        log.info(f"[yt-dlp] downloading first {sample_seconds}s of audio (sample mode) ...")
    else:
        log.info("[yt-dlp] downloading audio ...")
    dl_cmd = ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3",
              "--write-info-json",
              "-o", str(tmp / "%(id)s.%(ext)s"), url]
    if sample_seconds is not None:
        # yt-dlp clips to [start-end] via ffmpeg under the hood; we already
        # require ffmpeg for the whisper path so this is always available.
        dl_cmd += ["--download-sections", f"*0-{int(sample_seconds)}"]
    if log.level < V_VERBOSE:
        dl_cmd += ["--quiet", "--no-warnings"]
    dl = run(dl_cmd, log)
    if dl.returncode != 0:
        if log.level < V_VERBOSE and dl.stdout:
            print(_tail(dl.stdout), file=sys.stderr)
        die("yt-dlp failed to download audio. "
            "Common causes: invalid URL, private/age-restricted video, region block, "
            "or an outdated yt-dlp (try `brew upgrade yt-dlp`).",
            code=EXIT_DOWNLOAD)
    mp3s = sorted(glob.glob(str(tmp / "*.mp3")))
    if not mp3s:
        die("yt-dlp ran but produced no audio file", code=EXIT_DOWNLOAD)
    audio = mp3s[0]

    # --- Whisper -------------------------------------------------------------
    # At medium+ verbosity we let whisper stream its per-segment output
    # ([HH:MM:SS.sss --> HH:MM:SS.sss] text) directly to stderr so the user
    # sees continuous progress. At silent verbosity we suppress it and only
    # surface the tail on failure.
    log.info(f"[whisper] transcribing with model={model} ...")
    wh_cmd = ["whisper", audio, "--model", model, "--output_format", "txt",
              "--output_dir", str(tmp)]
    if log.level <= V_SILENT:
        wh_cmd += ["--verbose", "False"]
        wh_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True}
    else:
        # medium or verbose: inherit stdout/stderr so whisper streams live.
        wh_kwargs = {}

    wh = subprocess.run(wh_cmd, check=False, **wh_kwargs)
    if wh.returncode != 0:
        if wh_kwargs and getattr(wh, "stdout", None):
            print(_tail(wh.stdout), file=sys.stderr)
        die(f"whisper failed to transcribe (model={model}). "
            "If this is a model-name error, try one of: tiny, base, small, medium, large.",
            code=EXIT_WHISPER)
    txts = sorted(glob.glob(str(tmp / "*.txt")))
    if not txts:
        die("whisper ran but produced no .txt output", code=EXIT_WHISPER)
    text = Path(txts[0]).read_text(encoding="utf-8", errors="replace")
    return text, duration_s, estimate


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yt-transcript",
        description="Turn a YouTube video into a clean text transcript.",
    )
    p.add_argument("--version", action="version", version=f"yt-transcript {__version__}")
    p.add_argument("url", nargs="?", default=None,
                   help="YouTube video URL. Optional when --sample is used "
                        f"(defaults to {DEFAULT_SAMPLE_URL} in that case).")
    p.add_argument("--sample", action="store_true",
                   help=f"sample mode: only process the first N seconds "
                        f"(default {DEFAULT_SAMPLE_SECONDS}, see --sample-seconds). "
                        "Useful for smoke-testing the CLI end to end. "
                        "If no URL is given, a built-in sample URL is used.")
    p.add_argument("--sample-seconds", type=int, default=None, metavar="N",
                   help=f"length of the sample in seconds (default: {DEFAULT_SAMPLE_SECONDS}). "
                        "Implies --sample.")
    p.add_argument("--source", choices=SOURCES, default="auto",
                   help="transcript source (default: auto — uploaded → auto-captions → whisper)")
    p.add_argument("--lang", default="en", help="caption language code (default: en)")
    p.add_argument("--model", default="small", help="whisper model (default: small)")
    p.add_argument("--format", choices=FORMATS, default="txt", dest="format",
                   help="output format (default: txt). json emits a structured object "
                        "with video metadata, the source actually used, and the transcript.")
    p.add_argument("-o", "--output", help="write output to FILE instead of stdout")
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
    url: str, source: str, lang: str, model: str, tmp: Path, log: Logger,
    sample_seconds: int | None = None,
) -> Result:
    """Run the pipeline and return a populated Result.

    If sample_seconds is set, captions are truncated to cues starting before
    that time, and whisper processes only the first sample_seconds of audio.
    """

    def _caption_text(vtt: Path) -> str:
        return vtt_to_text(vtt, max_seconds=float(sample_seconds) if sample_seconds else None)

    def _result(text: str, actual_source: str, *, used_lang: str | None = None,
                used_model: str | None = None,
                audio_duration_seconds: float | None = None,
                whisper_estimate_seconds: dict | None = None) -> Result:
        meta = _meta_from_info(_read_info_json(tmp))
        return Result(
            transcript=text,
            source=actual_source,
            language=used_lang,
            model=used_model,
            audio_duration_seconds=audio_duration_seconds,
            whisper_estimate_seconds=whisper_estimate_seconds,
            **meta,
        )

    if source == "uploaded":
        log.info("[captions] fetching uploaded captions ...")
        vtt = try_captions(url, tmp, lang, log, uploaded=True, auto=False)
        if not vtt:
            die(f"no uploaded captions found for lang={lang!r}. "
                "Try --source auto-captions, --source whisper, or a different --lang.",
                code=EXIT_NO_CAPTIONS)
        return _result(_caption_text(vtt), "uploaded", used_lang=lang)

    if source == "auto-captions":
        log.info("[captions] fetching auto-generated captions ...")
        vtt = try_captions(url, tmp, lang, log, uploaded=False, auto=True)
        if not vtt:
            die(f"no auto-generated captions found for lang={lang!r}. "
                "Try --source whisper or a different --lang.",
                code=EXIT_NO_CAPTIONS)
        return _result(_caption_text(vtt), "auto-captions", used_lang=lang)

    if source == "whisper":
        text, dur, est = transcribe_with_whisper(
            url, tmp, model, log, sample_seconds=sample_seconds,
        )
        return _result(text, "whisper", used_model=model,
                       audio_duration_seconds=dur, whisper_estimate_seconds=est)

    # auto: uploaded -> auto-captions -> whisper
    log.info("[auto] trying uploaded captions ...")
    vtt = try_captions(url, tmp, lang, log, uploaded=True, auto=False)
    if vtt:
        return _result(_caption_text(vtt), "uploaded", used_lang=lang)  # auto-fallback hit uploaded
    for f in glob.glob(str(tmp / "*.vtt")):
        os.remove(f)

    log.info("[auto] trying auto-generated captions ...")
    vtt = try_captions(url, tmp, lang, log, uploaded=False, auto=True)
    if vtt:
        return _result(_caption_text(vtt), "auto-captions", used_lang=lang)

    log.info("[auto] no captions; falling back to whisper ...")
    text, dur, est = transcribe_with_whisper(
        url, tmp, model, log, sample_seconds=sample_seconds,
    )
    return _result(text, "whisper", used_model=model,
                   audio_duration_seconds=dur, whisper_estimate_seconds=est)


def main() -> None:
    args = build_parser().parse_args()
    log = Logger(_V_MAP[args.verbosity])

    # --- sample mode resolution ---------------------------------------------
    # --sample-seconds implies --sample.
    if args.sample_seconds is not None:
        args.sample = True
    sample_seconds: int | None = None
    if args.sample:
        sample_seconds = args.sample_seconds if args.sample_seconds is not None \
            else DEFAULT_SAMPLE_SECONDS
        if sample_seconds <= 0:
            die("--sample-seconds must be a positive integer", code=EXIT_USAGE)

    # --- URL resolution ------------------------------------------------------
    if not args.url:
        if args.sample:
            args.url = DEFAULT_SAMPLE_URL
            log.info(f"[sample] no URL given, using default: {args.url}")
        else:
            die("missing URL. Pass a YouTube URL, or use --sample to smoke-test "
                f"with the built-in default ({DEFAULT_SAMPLE_URL}).",
                code=EXIT_USAGE)

    validate_url(args.url)
    preflight(args.source)

    if sample_seconds is not None:
        log.info(f"[sample] truncating to first {sample_seconds}s")

    tmp = Path(tempfile.mkdtemp(prefix="yt-transcript-"))
    try:
        result = resolve_transcript(
            args.url, args.source, args.lang, args.model, tmp, log,
            sample_seconds=sample_seconds,
        )

        if args.format == "json":
            payload = {
                "transcript": result.transcript,
                "source": result.source,
                "language": result.language,
                "model": result.model,
                "video_id": result.video_id,
                "title": result.title,
                "duration": result.duration,
                "uploader": result.uploader,
                "webpage_url": result.webpage_url,
                "chars": len(result.transcript),
                # Whisper-only fields (null for caption sources).
                "audio_duration_seconds": result.audio_duration_seconds,
                "whisper_estimate_seconds": result.whisper_estimate_seconds,
                # Sample-mode metadata (null when sample mode is off).
                "sample": bool(args.sample),
                "sample_seconds": sample_seconds,
            }
            body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        else:
            body = result.transcript

        if args.output:
            try:
                Path(args.output).write_text(body, encoding="utf-8")
            except OSError as e:
                die(f"could not write output file {args.output!r}: {e}", code=EXIT_IO)
            # Outcome line: shown at every level (including silent).
            print(
                f"wrote {args.output} ({len(result.transcript)} chars, source={result.source})",
                file=sys.stderr,
            )
        else:
            sys.stdout.write(body)
        if args.keep_temp:
            print(f"[keep-temp] {tmp}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(EXIT_INTERRUPT)
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
