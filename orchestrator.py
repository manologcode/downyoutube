#!/usr/bin/env python3
"""Cliente del orquestador: envía textos y audios sin esperar resultado."""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from pathlib import Path

import requests

DEFAULT_URL = "http://192.168.1.69:8100"
DEFAULT_TEXT_ACTIONS = ["summarize"]
DEFAULT_AUDIO_ACTIONS = ["transcribe", "summarize"]

BASE_URL = os.environ.get("ORCHESTRATOR_URL", DEFAULT_URL).rstrip("/")
TIMEOUT = float(os.environ.get("ORCHESTRATOR_TIMEOUT", "120"))
_ENABLED = os.environ.get("ORCHESTRATOR_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def _json_env(name: str, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"[orquestador] {name} no es JSON válido; se usa {default!r}", flush=True)
        return default


def _actions_env(name: str, default: list[str]) -> list[str]:
    value = _json_env(name, default)
    if not isinstance(value, list):
        print(f"[orquestador] {name} debe ser una lista JSON; se usa {default!r}", flush=True)
        return list(default)
    actions = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not actions:
        print(f"[orquestador] {name} está vacío; se usa {default!r}", flush=True)
        return list(default)
    return actions


def _params_env(name: str) -> dict:
    value = _json_env(name, {})
    if not isinstance(value, dict):
        print(f"[orquestador] {name} debe ser un objeto JSON; se ignora", flush=True)
        return {}
    return value


TEXT_ACTIONS = _actions_env("ORCHESTRATOR_TEXT_ACTIONS", DEFAULT_TEXT_ACTIONS)
AUDIO_ACTIONS = _actions_env("ORCHESTRATOR_AUDIO_ACTIONS", DEFAULT_AUDIO_ACTIONS)
TEXT_PARAMS = _params_env("ORCHESTRATOR_TEXT_PARAMS")
AUDIO_PARAMS = _params_env("ORCHESTRATOR_AUDIO_PARAMS")


def is_enabled() -> bool:
    return _ENABLED and bool(BASE_URL)


def submit_text(path: Path | str) -> None:
    """Envía el contenido de un archivo de texto al orquestador."""
    if not is_enabled():
        return
    _spawn(_send_text, Path(path))


def submit_audio(path: Path | str) -> None:
    """Envía un archivo de audio al orquestador."""
    if not is_enabled():
        return
    _spawn(_send_file, Path(path))


def _spawn(target, *args) -> None:
    threading.Thread(target=_safe, args=(target, *args), daemon=True).start()


def _safe(target, *args) -> None:
    try:
        target(*args)
    except Exception as exc:  # noqa: BLE001 - se registra y no afecta a la descarga
        print(f"[orquestador] no se pudo enviar {args[0] if args else ''}: {exc}", flush=True)


def _payload(text: str, actions: list[str], params: dict) -> dict:
    return {
        "text": text,
        "actions": actions,
        "params": params,
        "priority": 0,
    }


def _send_text(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[orquestador] no se pudo leer {path}: {exc}", flush=True)
        return
    if _post(_payload(text, TEXT_ACTIONS, TEXT_PARAMS)):
        print(f"[orquestador] texto enviado: {path.name}", flush=True)


def _send_file(path: Path) -> None:
    if not path.is_file():
        print(f"[orquestador] archivo no encontrado: {path}", flush=True)
        return
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as fh:
        ok = _post(
            _payload("", AUDIO_ACTIONS, AUDIO_PARAMS),
            files={"file": (path.name, fh, mime)},
        )
    if ok:
        print(f"[orquestador] audio enviado: {path.name}", flush=True)


def _post(payload: dict, files: dict | None = None) -> bool:
    response = requests.post(
        f"{BASE_URL}/tasks",
        data={"payload": json.dumps(payload, ensure_ascii=False)},
        files=files,
        timeout=TIMEOUT,
    )
    if response.ok:
        return True
    print(
        f"[orquestador] respuesta {response.status_code}: {response.text[:400]}",
        flush=True,
    )
    return False
