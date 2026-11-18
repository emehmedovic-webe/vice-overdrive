"""Gemeinsame Helfer: Konfiguration, HTTP, Zeit, Secrets aus Umgebungsvariablen."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def secret(name: str) -> str:
    """Liest ein Secret ausschließlich aus der Umgebung (nie aus Dateien im Repo)."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Secret {name} fehlt. Als Umgebungsvariable bzw. Repository-Secret setzen, "
            "niemals in den Chat oder ins Repo schreiben."
        )
    return value


def read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def http_json(method: str, url: str, *, headers: dict | None = None,
              params: dict | list | None = None, body=None, form: dict | None = None,
              timeout: int = 30):
    """Kleiner JSON-HTTP-Client ohne Fremdpakete."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} bei {method} {url.split('?')[0]}: {detail}") from None
    return json.loads(raw) if raw else {}

def media_env() -> dict[str, str]:
    """Werkzeuge für Mediendateien erhalten keine Radar- oder Upload-Zugangsdaten."""
    return {k: os.environ[k] for k in (
        "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
    ) if k in os.environ}
