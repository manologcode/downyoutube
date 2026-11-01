#!/usr/bin/env python3
"""Interfaz web de downyoutube."""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

import downloader
import orchestrator

OUTPUT_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_FORMATS = ["mp3", "original", "m4a", "wav", "opus"]
DEFAULT_LANGS = "es,en"
MAX_URLS = 25
MAX_JOBS = 50

FINISHED_STATUSES = {"done", "error", "cancelled"}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_download_lock = threading.Lock()


class JobCancelled(Exception):
    """Se lanza desde los hooks de yt-dlp para abortar una descarga."""


def _now() -> float:
    return time.time()


def _public_job(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "mode": job["mode"],
        "urls": list(job["urls"]),
        "current": job["current"],
        "message": job["message"],
        "progress": dict(job["progress"]),
        "results": [
            {
                "url": result["url"],
                "status": result["status"],
                "error": result["error"],
                "files": list(result["files"]),
            }
            for result in job["results"]
        ],
        "error": job["error"],
        "created": job["created"],
        "finished": job["finished"],
    }


def _snapshot(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return _public_job(job) if job else None


def _prune_jobs() -> None:
    if len(_jobs) <= MAX_JOBS:
        return
    finished = sorted(
        (job for job in _jobs.values() if job["status"] in FINISHED_STATUSES),
        key=lambda job: job["finished"] or job["created"],
    )
    while len(_jobs) > MAX_JOBS and finished:
        _jobs.pop(finished.pop(0)["id"], None)


def _mark_cancelled(job: dict) -> None:
    for result in job["results"]:
        if result["status"] in {"pending", "running"}:
            result["status"] = "cancelled"
    job["status"] = "cancelled"
    job["message"] = "Cancelado."
    job["finished"] = _now()


def _cleanup_partials(since: float) -> None:
    try:
        entries = list(OUTPUT_DIR.iterdir())
    except OSError:
        return
    for path in entries:
        if not path.is_file():
            continue
        if ".part" not in path.name and path.suffix not in {".ytdl", ".temp"}:
            continue
        try:
            if path.stat().st_mtime >= since - 2:
                path.unlink()
        except OSError:
            continue


def _parse_payload(data: dict) -> dict:
    raw_urls = data.get("urls", "")
    if isinstance(raw_urls, list):
        urls = [str(url).strip() for url in raw_urls if str(url).strip()]
    else:
        urls = str(raw_urls).split()

    if not urls:
        raise ValueError("Introduce al menos una URL.")
    if len(urls) > MAX_URLS:
        raise ValueError(f"Máximo {MAX_URLS} URLs por descarga.")
    for url in urls:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"URL no válida: {url}")

    mode = data.get("mode", "video")
    if mode not in {"video", "audio", "txt"}:
        raise ValueError("Modo de descarga no válido.")

    quality = data.get("quality", "best")
    if quality not in downloader.QUALITIES:
        raise ValueError("Calidad no válida.")

    audio_format = data.get("audio_format", "mp3")
    if audio_format not in AUDIO_FORMATS:
        raise ValueError("Formato de audio no válido.")

    langs = downloader.parse_langs(str(data.get("langs") or DEFAULT_LANGS))

    cookie_file = OUTPUT_DIR / "cookies.txt"
    return {
        "urls": urls,
        "mode": mode,
        "quality": quality,
        "audio_format": audio_format,
        "langs": langs,
        "playlist": bool(data.get("playlist")),
        "cookies": str(cookie_file) if cookie_file.is_file() else None,
    }


def _progress_hooks(job: dict) -> list:
    def on_progress(data: dict) -> None:
        if job["cancel"]:
            raise JobCancelled()
        filename = Path(data.get("filename") or "").name or None
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = round(downloaded * 100.0 / total, 1) if total else 0.0
            with _jobs_lock:
                job["progress"] = {
                    "percent": percent,
                    "speed": data.get("speed"),
                    "eta": data.get("eta"),
                    "filename": filename,
                }
                job["message"] = f"Descargando {filename}" if filename else "Descargando..."
        elif data.get("status") == "finished":
            with _jobs_lock:
                job["progress"].update(
                    {"percent": 100.0, "speed": None, "eta": 0, "filename": filename}
                )
                job["message"] = "Procesando archivo..."

    return [on_progress]


def _send_to_orchestrator(mode: str, files: list[Path]) -> None:
    if mode == "audio":
        for path in files:
            orchestrator.submit_audio(path)
    elif mode == "txt":
        for path in files:
            orchestrator.submit_text(path)


def _download_one(job: dict, index: int) -> None:
    url = job["urls"][index]
    options = job["options"]

    with _jobs_lock:
        job["current"] = index
        job["results"][index]["status"] = "running"
        job["progress"] = {"percent": 0.0, "speed": None, "eta": None, "filename": None}
        job["message"] = f"Obteniendo información de {url}"

    if job["mode"] == "txt":
        files = downloader.download_text(
            url,
            OUTPUT_DIR,
            options["langs"],
            cookies=options["cookies"],
            playlist=options["playlist"],
        )
    else:
        files = downloader.download_media(
            url,
            OUTPUT_DIR,
            audio=job["mode"] == "audio",
            quality=options["quality"],
            audio_format=options["audio_format"],
            cookies=options["cookies"],
            playlist=options["playlist"],
            progress_hooks=_progress_hooks(job),
        )

    names = [path.name for path in files]
    with _jobs_lock:
        job["results"][index]["status"] = "done"
        job["results"][index]["files"] = names
        job["progress"] = {
            "percent": 100.0,
            "speed": None,
            "eta": 0,
            "filename": names[0] if names else job["progress"].get("filename"),
        }
        job["message"] = "Descarga completada."

    _send_to_orchestrator(job["mode"], files)


def _run_job(job_id: str) -> None:
    while not _download_lock.acquire(timeout=0.5):
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            if job["cancel"]:
                _mark_cancelled(job)
                return
            job["message"] = "En cola: otra descarga está en curso..."

    try:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            if job["cancel"]:
                _mark_cancelled(job)
                return
            job["status"] = "running"
            job["started"] = _now()
            job["message"] = "Iniciando descarga..."

        for index in range(len(job["urls"])):
            with _jobs_lock:
                if job["cancel"]:
                    raise JobCancelled()
            try:
                _download_one(job, index)
            except JobCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - se muestra al usuario
                with _jobs_lock:
                    job["results"][index]["status"] = "error"
                    job["results"][index]["error"] = downloader.short_error(exc)
                    job["message"] = f"Error en {job['urls'][index]}"

        with _jobs_lock:
            errors = sum(1 for result in job["results"] if result["status"] == "error")
            if errors == len(job["results"]):
                job["status"] = "error"
                job["message"] = "Todas las descargas fallaron."
            else:
                job["status"] = "done"
                job["message"] = (
                    "Descarga completada."
                    if errors == 0
                    else f"Completado con {errors} error(es)."
                )
            job["finished"] = _now()
    except JobCancelled:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                _mark_cancelled(job)
                since = job.get("started") or job["created"]
            else:
                since = _now()
        _cleanup_partials(since)
    finally:
        _download_lock.release()


def _safe_output_path(filename: str) -> Path | None:
    base = OUTPUT_DIR.resolve()
    path = (base / filename).resolve()
    if path.parent != base:
        return None
    if not path.is_file() or path.name == "cookies.txt":
        return None
    return path


@app.get("/")
def index():
    return render_template(
        "index.html",
        qualities=list(downloader.QUALITIES),
        audio_formats=AUDIO_FORMATS,
        default_langs=DEFAULT_LANGS,
        orchestrator_enabled=orchestrator.is_enabled(),
    )


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/api/jobs")
def create_job():
    data = request.get_json(silent=True) or {}
    try:
        options = _parse_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "queued",
        "mode": options["mode"],
        "urls": options["urls"],
        "current": 0,
        "message": "En cola...",
        "progress": {"percent": 0.0, "speed": None, "eta": None, "filename": None},
        "results": [
            {"url": url, "status": "pending", "error": None, "files": []}
            for url in options["urls"]
        ],
        "error": None,
        "created": _now(),
        "started": None,
        "finished": None,
        "cancel": False,
        "options": options,
    }
    with _jobs_lock:
        _prune_jobs()
        _jobs[job_id] = job

    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return jsonify({"id": job_id, "job": _snapshot(job_id)}), 202


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = _snapshot(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado."}), 404
    return jsonify(job)


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Trabajo no encontrado."}), 404
        if job["status"] in FINISHED_STATUSES:
            return jsonify({"error": "La descarga ya ha terminado."}), 400
        job["cancel"] = True
        job["message"] = "Cancelando..."
    return jsonify({"ok": True})


@app.get("/api/files")
def list_files():
    try:
        entries = sorted(
            OUTPUT_DIR.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True
        )
    except OSError:
        entries = []

    files = []
    for path in entries:
        if not path.is_file() or path.name == "cookies.txt" or path.name.startswith("."):
            continue
        if path.suffix in {".part", ".ytdl", ".temp"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "url": url_for("download_file", filename=path.name),
            }
        )
    return jsonify({"files": files})


@app.get("/files/<path:filename>")
def download_file(filename: str):
    path = _safe_output_path(filename)
    if not path:
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), path.name, as_attachment=True)


@app.delete("/api/files/<path:filename>")
def delete_file(filename: str):
    path = _safe_output_path(filename)
    if not path:
        return jsonify({"error": "Archivo no encontrado."}), 404
    try:
        path.unlink()
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True})


if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", "8080"))
    print(f"downyoutube web escuchando en http://0.0.0.0:{port}", flush=True)
    serve(app, host="0.0.0.0", port=port, threads=8)
