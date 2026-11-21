"""Local-only configuration dashboard for Donna.

The dashboard is deliberately a separate application: it is never mounted on the
public webhook server. It listens on loopback, rejects foreign Host/Origin headers,
masks every secret and writes the env file atomically with 0600 permissions.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import secrets
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from .config import Settings, PROJECT_ROOT

GROUP_LABELS = {
    "ema": "EMA / Donna",
    "meta": "Meta (Graph API)",
    "wa": "WhatsApp Cloud API",
    "ig": "Instagram",
    "threads": "Threads",
}

# Estos campos son de consulta: activar envío real o cambiar la clave maestra
# queda fuera del panel y exige editar el entorno del contenedor a mano.
PROTECTED_FIELDS = frozenset({"EMA_LIVE", "WA_ACCESS_TOKEN", "EMA_MASTER_KEY"})
SECRET_MARKERS = ("secret", "access_token", "password", "credential", "master_key")
EXPANSION_RE = re.compile(r"\$(?:\{|[A-Za-z_])")
FORWARDED_HEADERS = (
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
)

DEFAULT_PROFILE = {
    "name": "Allan Odreman",
    "role": "Operador — Edge Marketing",
    "timezone": "America/Guayaquil",
    "notes": "Donna responde automáticamente solo agenda/venta; el resto escala a humano.",
}

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; img-src data:; form-action 'self'"
    ),
}


def _is_loophost(host: str) -> bool:
    host = host.strip().lower()
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host in {"127.0.0.1", "localhost", "::1"}


def _env_key(field_name: str) -> str:
    return field_name.upper()


async def _form(request: Request) -> dict[str, str]:
    """Parse urlencoded forms without adding python-multipart to the image."""
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        return {}
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def _field_kind(field: FieldInfo, name: str = "") -> str:
    annotation = str(field.annotation)
    if "SecretStr" in annotation or any(marker in name.lower() for marker in SECRET_MARKERS):
        return "secret"
    if "bool" in annotation:
        return "bool"
    if "int" in annotation:
        return "int"
    if "float" in annotation:
        return "float"
    return "str"


def _field_groups(settings: Settings) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for name, field in Settings.model_fields.items():
        prefix = name.split("_", 1)[0]
        group = prefix if prefix in GROUP_LABELS else "ema"
        kind = _field_kind(field, name)
        key = _env_key(name)
        value = getattr(settings, name)
        if kind == "secret":
            display = "••••••••" if value and value.get_secret_value() else ""
            configured = bool(value and value.get_secret_value())
        else:
            display = "" if value is None else str(value)
            configured = bool(display)
        groups.setdefault(group, []).append(
            {
                "key": key,
                "label": name,
                "kind": kind,
                "value": display,
                "configured": configured,
                "readonly": key in PROTECTED_FIELDS,
            }
        )
    for items in groups.values():
        items.sort(key=lambda item: item["key"])
    return groups


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return lines, values


def _env_values(path: Path) -> dict[str, str]:
    """Read only the file, without process-environment interpolation."""
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None}


def _quote(value: str) -> str:
    """Double-quote with JSON escapes; accepted by python-dotenv."""
    return json.dumps(value, ensure_ascii=False)


def _apply_env(
    path: Path,
    updates: Mapping[str, str],
    clears: set[str],
) -> list[str]:
    """Rewrite the env file in place, atomically, preserving unrelated lines."""
    lines, _ = _read_env(path)
    handled: set[str] = set()
    output: list[str] = []
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else None
        if key in clears:
            handled.add(key)
            continue
        if key in updates:
            handled.add(key)
            output.append(f"{key}={_quote(updates[key])}")
            continue
        output.append(line)
    remaining = [key for key in updates if key not in handled]
    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.append("# Actualizado por el panel local de Donna")
        output.extend(f"{key}={_quote(updates[key])}" for key in sorted(remaining))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".ema-env-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return sorted(set(updates) | clears)


def _audit(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": "donna-dashboard",
        "action": "config_update",
        "keys": keys,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def _load_profile(path: Path) -> dict[str, str]:
    profile = dict(DEFAULT_PROFILE)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                for key in profile:
                    if isinstance(stored.get(key), str):
                        profile[key] = stored[key]
        except (json.JSONDecodeError, OSError):
            pass
    return profile


def _save_profile(path: Path, profile: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".ema-profile-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _diagnostics(settings: Settings) -> list[tuple[str, str, str]]:
    """Return (label, state, detail) rows; never include secret values."""
    allowlist = settings.allowlist
    phone_ok = settings.wa_phone_number_id.lower() in allowlist if settings.wa_phone_number_id else False
    return [
        (
            "Modo de envío",
            "ok" if not settings.ema_live else "warn",
            "EMA_LIVE=true — envío real habilitado" if settings.ema_live else "EMA_LIVE=false — solo borradores",
        ),
        (
            "Firma HMAC WhatsApp",
            "ok" if settings.secret(settings.wa_app_secret) else "bad",
            "WA_APP_SECRET disponible para /webhooks/whatsapp"
            if settings.secret(settings.wa_app_secret)
            else "Falta WA_APP_SECRET",
        ),
        (
            "Verify token WhatsApp",
            "ok" if settings.secret(settings.wa_webhook_verify_token) else "bad",
            "WA_WEBHOOK_VERIFY_TOKEN configurado"
            if settings.secret(settings.wa_webhook_verify_token)
            else "Falta WA_WEBHOOK_VERIFY_TOKEN",
        ),
        (
            "Firma HMAC Meta",
            "ok" if settings.secret(settings.meta_app_secret) else "warn",
            "META_APP_SECRET disponible para /webhooks/meta"
            if settings.secret(settings.meta_app_secret)
            else "Falta META_APP_SECRET (no afecta a WhatsApp)",
        ),
        (
            "Verify token Meta",
            "ok" if settings.secret(settings.meta_webhook_verify_token) else "warn",
            "META_WEBHOOK_VERIFY_TOKEN configurado"
            if settings.secret(settings.meta_webhook_verify_token)
            else "Falta META_WEBHOOK_VERIFY_TOKEN (no afecta a WhatsApp)",
        ),
        (
            "Token de envío WA",
            "ok" if settings.secret(settings.wa_access_token) else "warn",
            "WA_ACCESS_TOKEN presente" if settings.secret(settings.wa_access_token) else "Pendiente: token de System User",
        ),
        (
            "Allowlist",
            "ok" if phone_ok else "bad",
            f"{len(allowlist)} número(s); el teléfono configurado {'está' if phone_ok else 'NO está'} incluido",
        ),
        (
            "Teléfono / WABA",
            "ok" if settings.wa_phone_number_id and settings.wa_waba_id else "warn",
            "IDs de WhatsApp presentes" if settings.wa_phone_number_id and settings.wa_waba_id else "IDs incompletos",
        ),
    ]


def _render_page(
    settings: Settings,
    groups: Mapping[str, list[dict[str, Any]]],
    profile: Mapping[str, str],
    diagnostics: list[tuple[str, str, str]],
    csrf: str,
    saved: bool,
) -> str:
    esc = html.escape
    pills = "".join(
        f'<li class="diag {state}"><span class="dot"></span><div><strong>{esc(label)}</strong>'
        f'<small>{esc(detail)}</small></div></li>'
        for label, state, detail in diagnostics
    )
    sections: list[str] = []
    for group, items in groups.items():
        rows: list[str] = []
        for item in items:
            key = item["key"]
            kind = item["kind"]
            label = esc(item["label"])
            readonly = bool(item.get("readonly"))
            if readonly:
                shown = (
                    "configurado" if kind == "secret" and item["configured"]
                    else "pendiente" if kind == "secret"
                    else "true" if item["value"].lower() == "true"
                    else "false" if kind == "bool"
                    else item["value"] or "—"
                )
                control = f'<span id="f-{key}" class="readonly">{esc(shown)}</span>'
            elif kind == "bool":
                checked = " checked" if item["value"].lower() == "true" else ""
                control = (
                    f'<label class="switch"><input id="f-{key}" type="checkbox" name="{key}" value="true"{checked}>'
                    f'<span></span></label><input type="hidden" name="__bool__{key}" value="1">'
                )
            elif kind in {"int", "float"}:
                control = (
                    f'<input id="f-{key}" type="number" name="{key}" value="{esc(item["value"])}" '
                    f'step="{"any" if kind == "float" else "1"}" autocomplete="off">'
                )
            elif kind == "secret":
                placeholder = "•••••••• (configurado)" if item["configured"] else "sin configurar"
                control = (
                    f'<input id="f-{key}" type="password" name="{key}" value="" '
                    f'placeholder="{placeholder}" autocomplete="new-password">'
                    f'<label class="clear"><input type="checkbox" name="__clear__{key}" value="1"> limpiar</label>'
                )
            else:
                control = (
                    f'<input id="f-{key}" type="text" name="{key}" value="{esc(item["value"])}" '
                    f'autocomplete="off" spellcheck="false">'
                )
            badge = '<span class="tag secret">secreto</span>' if kind == "secret" else ""
            if readonly:
                badge += '<span class="tag lock">solo lectura</span>'
            state = '<span class="tag on">activo</span>' if item["configured"] else '<span class="tag">vacío</span>'
            rows.append(
                f'<div class="row"><label for="f-{key}">{label}{badge}</label>'
                f'<div class="control">{control}{state}</div></div>'
            )
        sections.append(
            f'<section class="card"><h2>{esc(GROUP_LABELS.get(group, group))}</h2>'
            f'<div class="rows">{"".join(rows)}</div></section>'
        )

    notice = '<div class="notice ok" role="status">Cambios guardados.</div>' if saved else ""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Donna · Configuración local</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1120; --card:#131c31; --line:#263452; --ink:#e8eefc;
  --muted:#93a4c4; --accent:#6ee7c7; --warn:#fbbf24; --bad:#fb7185; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:radial-gradient(1200px 600px at 10% -10%,#1b2b52,transparent),var(--bg);
  color:var(--ink); font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
a {{ color:var(--accent); }}
.wrap {{ max-width:1180px; margin:0 auto; padding:32px 20px 64px; }}
header {{ display:flex; flex-wrap:wrap; gap:18px; align-items:center; margin-bottom:24px; }}
.avatar {{ width:58px; height:58px; border-radius:18px; display:grid; place-items:center; font-size:26px;
  background:linear-gradient(145deg,#6ee7c7,#3b82f6); color:#06121f; font-weight:800; }}
h1 {{ font-size:24px; margin:0; }} h2 {{ font-size:16px; margin:0 0 14px; letter-spacing:.02em; }}
.sub {{ color:var(--muted); margin:2px 0 0; }}
.badge {{ margin-left:auto; padding:7px 12px; border-radius:999px; background:#10263a;
  border:1px solid #1e4b5f; color:var(--accent); font-size:12px; font-weight:700; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:18px; align-items:start; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px;
  box-shadow:0 12px 30px rgba(0,0,0,.18); }}
.card.profile {{ grid-column:1/-1; display:grid; grid-template-columns:1.2fr 1fr; gap:20px; }}
.profile-fields {{ display:grid; gap:10px; }}
.profile-fields label {{ display:block; font-size:12px; color:var(--muted); margin-bottom:3px; }}
input[type=text],input[type=password],input[type=number] {{ width:100%; padding:9px 11px; border-radius:9px;
  background:#0d1527; border:1px solid var(--line); color:var(--ink); font:inherit; }}
input:focus-visible,button:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
.rows {{ display:grid; gap:11px; max-height:560px; overflow:auto; padding-right:4px; }}
.row {{ display:grid; gap:5px; }}
.row label {{ font-size:12px; color:var(--muted); word-break:break-all; }}
.control {{ display:grid; grid-template-columns:1fr auto auto; gap:8px; align-items:center; }}
.switch input {{ position:absolute; opacity:0; }}
.switch span {{ display:inline-block; width:40px; height:22px; border-radius:99px; background:#33415c;
  position:relative; cursor:pointer; transition:background .15s; }}
.switch span::after {{ content:""; position:absolute; width:16px; height:16px; border-radius:50%;
  background:#fff; top:3px; left:3px; transition:transform .15s; }}
.switch input:checked + span {{ background:#0f8f78; }}
.switch input:checked + span::after {{ transform:translateX(18px); }}
.switch input:focus-visible + span {{ outline:2px solid var(--accent); outline-offset:2px; }}
.tag {{ font-size:10px; padding:2px 7px; border-radius:99px; border:1px solid var(--line); color:var(--muted); white-space:nowrap; }}
.tag.secret {{ color:var(--warn); border-color:#6b5423; }} .tag.on {{ color:var(--accent); border-color:#1e4b5f; }}
.tag.lock {{ color:#c4b5fd; border-color:#554681; }}
.readonly {{ padding:9px 11px; background:#0d1527; border:1px dashed var(--line); border-radius:9px; color:var(--muted); word-break:break-all; }}
.clear {{ font-size:11px; color:var(--muted); white-space:nowrap; }}
.diag {{ list-style:none; display:flex; gap:10px; padding:9px 0; border-bottom:1px solid var(--line); }}
.diag:last-child {{ border:0; }} .diag small {{ display:block; color:var(--muted); }}
.dot {{ width:9px; height:9px; border-radius:50%; margin-top:6px; background:var(--muted); flex:none; }}
.diag.ok .dot {{ background:var(--accent); }} .diag.warn .dot {{ background:var(--warn); }}
.diag.bad .dot {{ background:var(--bad); }}
button {{ margin-top:16px; padding:10px 18px; border:0; border-radius:10px; font-weight:700;
  background:var(--accent); color:#06121f; cursor:pointer; }}
button.secondary {{ background:#243354; color:var(--ink); }}
.notice {{ padding:11px 14px; border-radius:10px; margin-bottom:16px; }}
.notice.ok {{ background:#10372f; border:1px solid #1e6b5b; color:var(--accent); }}
footer {{ color:var(--muted); font-size:12px; margin-top:24px; }}
@media (max-width:720px) {{ .card.profile {{ grid-template-columns:1fr; }} .badge {{ margin-left:0; }} }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="avatar" aria-hidden="true">D</div>
  <div><h1>Donna · consola local</h1><p class="sub">Configuración de {esc(profile["name"])} · {esc(profile["role"])}</p></div>
  <span class="badge">SOLO LOCAL · 127.0.0.1</span>
</header>
{notice}
<div class="grid">
  <section class="card profile">
    <div><h2>Perfil personal</h2>
      <div class="profile-fields">
        <form method="post" action="/profile" id="profile-form">
          <input type="hidden" name="csrf" value="{csrf}">
          <label for="p-name">Nombre</label><input id="p-name" name="name" value="{esc(profile["name"])}">
          <label for="p-role">Rol</label><input id="p-role" name="role" value="{esc(profile["role"])}">
          <label for="p-tz">Zona horaria</label><input id="p-tz" name="timezone" value="{esc(profile["timezone"])}">
          <label for="p-notes">Notas</label><input id="p-notes" name="notes" value="{esc(profile["notes"])}">
          <button type="submit" class="secondary">Guardar perfil</button>
        </form>
      </div>
    </div>
    <div><h2>Diagnóstico</h2><ul>{pills}</ul></div>
  </section>
  {''.join(sections)}
</div>
<form method="post" action="/save">
  <input type="hidden" name="csrf" value="{csrf}">
  <button type="submit">Guardar configuración</button>
</form>
<footer>Los secretos nunca se muestran ni se rellenan: déjelos vacíos para conservarlos.
Los campos <em>solo lectura</em> (EMA_LIVE, WA_ACCESS_TOKEN, EMA_MASTER_KEY) se cambian
en el entorno del contenedor, no aquí. El panel no está expuesto al túnel público; el webhook firmado sigue en
<code>https://donna.edgemarketing.tech/webhooks/whatsapp</code>.</footer>
</div>
</body>
</html>"""


def create_dashboard_app(
    settings: Settings,
    *,
    env_path: Path | None = None,
    profile_path: Path | None = None,
    audit_path: Path | None = None,
) -> FastAPI:
    """Build the loopback-only dashboard application."""
    env_file = env_path or PROJECT_ROOT / ".env"
    data_dir = settings.ema_audit_file.parent
    profile_file = profile_path or data_dir / "donna-profile.json"
    audit_file = audit_path or data_dir / "config-audit.jsonl"
    csrf = secrets.token_urlsafe(32)
    app = FastAPI(title="Donna · consola local", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.csrf = csrf
    app.state.save_lock = asyncio.Lock()

    def deny(message: str) -> PlainTextResponse:
        response = PlainTextResponse(message, status_code=403)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        return response

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Response:
        from urllib.parse import urlparse

        host = request.headers.get("host", "")
        if not _is_loophost(host):
            return deny("solo acceso local")
        if any(header in request.headers for header in FORWARDED_HEADERS):
            return deny("proxy no permitido")
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not _is_loophost(parsed.netloc):
                return deny("origen no permitido")
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        return response

    def current_settings() -> Settings:
        """Build Settings from the file only; process env must not override it."""
        if not env_file.exists():
            return settings
        try:
            return Settings.model_validate(_env_values(env_file))
        except ValidationError:
            return settings

    def page(saved: bool = False) -> str:
        current = current_settings()
        return _render_page(
            current,
            _field_groups(current),
            _load_profile(profile_file),
            _diagnostics(current),
            csrf,
            saved,
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(saved: int = 0) -> str:
        return page(bool(saved))

    @app.post("/save")
    async def save(request: Request) -> RedirectResponse:
        form = await _form(request)
        if str(form.get("csrf", "")) != csrf:
            raise HTTPException(status_code=403, detail="token CSRF inválido")
        known = {
            _env_key(name): field
            for name, field in Settings.model_fields.items()
            if _env_key(name) not in PROTECTED_FIELDS
        }
        updates: dict[str, str] = {}
        clears: set[str] = set()
        for key, field in known.items():
            kind = _field_kind(field, key.lower())
            if f"__clear__{key}" in form and kind == "secret":
                clears.add(key)
                continue
            if f"__bool__{key}" in form:
                updates[key] = "true" if key in form else "false"
                continue
            raw = form.get(key)
            if raw is None:
                continue
            value = str(raw) if kind == "secret" else str(raw).strip()
            if kind == "secret" and not value:
                continue
            if EXPANSION_RE.search(value):
                raise HTTPException(
                    status_code=400,
                    detail=f"expandición de variables no soportada en {key}",
                )
            updates[key] = value

        candidate = _env_values(env_file)
        for key in clears:
            candidate.pop(key, None)
        candidate.update(updates)
        try:
            Settings.model_validate(candidate)
        except ValidationError as exc:
            bad = ", ".join(sorted({str(error["loc"][0]) for error in exc.errors()}))
            raise HTTPException(status_code=400, detail=f"valor inválido en {bad}") from None

        async with app.state.save_lock:
            changed = _apply_env(env_file, updates, clears)
            _audit(audit_file, changed)
        return RedirectResponse("/?saved=1", status_code=303)

    @app.post("/profile")
    async def save_profile(request: Request) -> RedirectResponse:
        form = await _form(request)
        if str(form.get("csrf", "")) != csrf:
            raise HTTPException(status_code=403, detail="token CSRF inválido")
        profile = {key: str(form.get(key, ""))[:300] for key in DEFAULT_PROFILE}
        async with app.state.save_lock:
            _save_profile(profile_file, profile)
        return RedirectResponse("/?saved=1", status_code=303)

    return app
