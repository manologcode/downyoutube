#!/usr/bin/env python3
"""downyoutube - motor de descargas de vídeo, audio y subtítulos de YouTube."""

from __future__ import annotations

import html
import re
import sys
import tempfile
import textwrap
import time
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit(
        "yt-dlp no está instalado.\n"
        "Instálalo con: pip install -r requirements.txt (o usa la imagen Docker)."
    )

QUALITIES = {
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    "2160": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1440": "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360]",
}

TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->")
TAG_RE = re.compile(r"<[^>]+>")
SPACES_RE = re.compile(r"[ \t]+")


def log(message: str = "") -> None:
    print(message, flush=True)


def parse_langs(value: str) -> list[str]:
    langs = [part.strip() for part in value.split(",") if part.strip()]
    return langs or ["es", "en"]


def download_media(
    url: str,
    out_dir: Path,
    *,
    audio: bool = False,
    quality: str = "best",
    audio_format: str = "mp3",
    cookies: str | None = None,
    playlist: bool = False,
    progress_hooks: list | None = None,
    postprocessor_hooks: list | None = None,
) -> list[Path]:
    files: list[str] = []

    def on_finished(data: dict) -> None:
        if data.get("status") == "finished" and data.get("filename"):
            files.append(data["filename"])

    def on_postprocessed(data: dict) -> None:
        if data.get("status") != "finished":
            return
        info = data.get("info_dict") or {}
        filepath = info.get("filepath") or info.get("_filename")
        if filepath:
            files.append(filepath)

    opts = {
        "outtmpl": str(out_dir / "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": not playlist,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [*(progress_hooks or []), on_finished],
        "postprocessor_hooks": [*(postprocessor_hooks or []), on_postprocessed],
    }
    if cookies:
        opts["cookiefile"] = cookies

    if audio:
        opts["format"] = "bestaudio/best"
        if audio_format != "original":
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            ]
    else:
        opts["format"] = QUALITIES[quality]
        opts["merge_output_format"] = "mp4/mkv"

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    result: list[Path] = []
    seen: set[str] = set()
    for raw in files:
        path = Path(raw)
        key = str(path.resolve())
        if path.is_file() and key not in seen:
            seen.add(key)
            result.append(path)
    return result


def download_text(
    url: str,
    out_dir: Path,
    langs: list[str],
    *,
    cookies: str | None = None,
    playlist: bool = False,
) -> list[Path]:
    with tempfile.TemporaryDirectory(prefix="downyoutube-") as tmp:
        tmp_dir = Path(tmp)
        info_opts = {
            "skip_download": True,
            "noplaylist": not playlist,
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "extractor_retries": 3,
        }
        if cookies:
            info_opts["cookiefile"] = cookies

        info = _extract_info(url, info_opts)
        entries = _video_entries(info)
        if not entries:
            raise RuntimeError("no se pudo obtener información del vídeo.")

        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "vtt",
            "outtmpl": str(tmp_dir / "%(title)s [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "extractor_retries": 3,
            "sleep_subtitles": 1,
        }
        if cookies:
            opts["cookiefile"] = cookies

        written: list[Path] = []
        errors: list[str] = []
        for entry in entries:
            title = entry.get("title") or entry.get("id") or "vídeo"
            lang = choose_subtitle_language(entry, langs)
            if not lang:
                errors.append(f"{title}: sin subtítulos en los idiomas pedidos")
                continue

            opts["subtitleslangs"] = [lang]
            before = set(tmp_dir.glob("*.vtt"))
            try:
                _download_subtitles(entry, opts)
            except yt_dlp.utils.DownloadError as exc:
                errors.append(f"{title}: {short_error(exc)}")
                continue

            new_files = sorted(set(tmp_dir.glob("*.vtt")) - before)
            if not new_files:
                errors.append(f"{title}: no se descargaron subtítulos")
                continue

            for source in new_files:
                text = vtt_to_text(source.read_text(encoding="utf-8", errors="replace"))
                if not text:
                    errors.append(f"{title}: subtítulos vacíos")
                    continue
                base = source.stem
                suffix = f".{lang}"
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
                destination = out_dir / f"{base}.txt"
                destination.write_text(text + "\n", encoding="utf-8")
                written.append(destination)
                log(f"[ok] {destination}")

        if written:
            for message in errors:
                log(f"[aviso] {message}")
            return written

        raise RuntimeError("; ".join(errors[:3]) if errors else "no hay subtítulos disponibles.")


def _video_entries(info: dict) -> list[dict]:
    entries = info.get("entries")
    if entries is not None:
        return [entry for entry in entries if isinstance(entry, dict)]
    return [info]


def _extract_info(url: str, opts: dict) -> dict:
    last_error: Exception | None = None
    for delay in (0, 3, 10, 25):
        if delay:
            time.sleep(delay)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            message = str(exc)
            if "429" not in message and "Too Many Requests" not in message:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("no se pudo obtener información del vídeo.")


def _match_language(available: dict, wanted: str) -> str | None:
    if wanted in available:
        return wanted
    for code in available:
        if code.startswith(f"{wanted}-"):
            return code
    return None


def choose_subtitle_language(info: dict, langs: list[str]) -> str | None:
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    for wanted in langs:
        for pool in (manual, automatic):
            match = _match_language(pool, wanted)
            if match:
                return match
    for pool in (manual, automatic):
        match = _match_language(pool, "en")
        if match:
            return match
    if manual:
        return next(iter(manual))
    if automatic:
        return next(iter(automatic))
    return None


def _download_subtitles(entry: dict, opts: dict) -> None:
    last_error: Exception | None = None
    for delay in (0, 3, 10, 25):
        if delay:
            time.sleep(delay)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.process_ie_result(entry, download=True)
            return
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            message = str(exc)
            if "429" not in message and "Too Many Requests" not in message:
                raise
    if last_error:
        raise last_error


def vtt_to_text(content: str) -> str:
    lines: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "Kind:", "Language:")):
            continue
        if TIMESTAMP_RE.match(line) or line.isdigit():
            continue
        line = html.unescape(TAG_RE.sub("", line))
        line = SPACES_RE.sub(" ", line).strip()
        if not line:
            continue
        if lines and line == lines[-1]:
            continue
        if lines and line.startswith(lines[-1]):
            lines[-1] = line
            continue
        lines.append(line)

    text = " ".join(lines)
    return textwrap.fill(text, width=110) if text else ""


def short_error(exc: Exception) -> str:
    message = " ".join(re.sub(r"^ERROR:\s*", "", str(exc)).split())
    if "429" in message or "Too Many Requests" in message:
        message += (
            " | YouTube está limitando las peticiones (HTTP 429): espera unos minutos, "
            "usa cookies (--cookies o downloads/cookies.txt) o prueba otra red."
        )
    return message if len(message) <= 700 else message[:700] + "..."
