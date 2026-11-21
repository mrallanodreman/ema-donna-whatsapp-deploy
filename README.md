# EMA Instagram + Threads

Núcleo API-first (F4/F5 del `PLAN.md`) para publicar, moderar, descubrir y medir en
Instagram Platform y Threads API, con freno de seguridad por defecto.

## Estado

- Implementado: configuración, cifrado de tokens, HMAC de webhooks, OAuth `state`,
  cliente Graph con reintentos/paginación, guardrails con auditoría, módulos
  Threads/Instagram, router FastAPI, orquestador y CLI.
- WhatsApp (Donna): webhook firmado, normalización dedicada, dedupe por `wamid`,
  clasificación, borradores y respuesta automática de `agenda`/`venta` vía
  `POST /{PHONE_NUMBER_ID}/messages` con guardrails.
- No implementado aún: recordatorios con consentimiento, Marketing API (opcional
  según PLAN), automatización UI vía BrowserOS (solo helpers, sin ejecución),
  App Review y credenciales reales.

## Arranque

```bash
cd /mnt/sda1/EdgeMarketing/ema-ig-threads
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python -m ema.security --generate-key   # pegar en EMA_MASTER_KEY
.venv/bin/pytest -q
.venv/bin/ema status
.venv/bin/ema watch                               # servidor de webhooks
```

`EMA_LIVE=false` por defecto: cualquier acción con efecto devuelve un plan
dry-run. Para ejecutar hacen falta tres condiciones simultáneas: `approve=True`,
`EMA_LIVE=true` y cuenta presente en `EMA_ALLOWLIST`.

## Despliegue

Imagen y Compose listos para Coolify; procedimiento y decisión sobre Embedded Signup en
[`docs/coolify-donna.md`](docs/coolify-donna.md).

## WhatsApp / Donna (draft-only)

```bash
.venv/bin/ema draft-whatsapp --text "quiero agendar una reunión"
.venv/bin/ema watch   # expone GET/POST /webhooks/whatsapp
```

- Verificación y firma usan `WA_APP_SECRET` / `WA_WEBHOOK_VERIFY_TOKEN` de la app
  de WhatsApp; si están vacíos caen a `META_APP_SECRET` / `META_WEBHOOK_VERIFY_TOKEN`
  solo en pruebas.
- El payload `whatsapp_business_account` se normaliza en `ema/whatsapp/`; no cae
  al fallback de Instagram/Threads. Duplicados por `wamid` mediante `EventStore`.
- Cada mensaje entrante produce un borrador y una línea de auditoría
  `draft_whatsapp`. Los intents `agenda` y `venta` se responden solos; el resto
  queda para revisión humana.
- El envío solo ocurre si `EMA_LIVE=true`, `WA_ACCESS_TOKEN` está configurado y
  `WA_PHONE_NUMBER_ID` está en `EMA_ALLOWLIST`. Sin esas tres condiciones el
  webhook devuelve `sent: false` con el motivo, sin llamar a Graph.
- Reglas de tono, agenda y escalado: `docs/donna-language-manual.md`.
- Panel de configuración **solo local**: `.venv/bin/ema dashboard` →
  `http://127.0.0.1:8098`. No se expone por el túnel público; ver
  `docs/donna-dashboard.md`.

## Seguridad

- Secretos solo por ENV/vault; `.env` está ignorado por git.
- Tokens cifrados con Fernet en `EMA_TOKEN_FILE` (permisos 0600).
- Webhooks verificados con `X-Hub-Signature-256` (HMAC SHA-256 + `compare_digest`).
- `state` OAuth firmado, con nonce de un solo uso y expiración corta.
- Audit log JSONL append-only en `EMA_AUDIT_FILE`.
- El log no imprime tokens; `/status` devuelve configuración sanitizada.

## Decisiones de diseño

- Un único `MetaClient` asíncono parametrizable por base URL y `httpx.Transport`,
  lo que permite tests sin red y reutilizar la lógica de errores en ambas APIs.
- Normalizadores de eventos en `ema/events.py` y adaptadores por plataforma;
  el router de webhooks no conoce detalles de Graph.
- Los efectos se ejecutan mediante un *callable* diferido pasado a `Guardrails`,
  así un plan rechazado nunca llega a construir la petición.
- Nombres de parámetros de campos avanzados (poll, spoiler, geo-gate, etc.)
  siguen la documentación vigente; verificar contra la versión de Graph
  configurada antes de activar live mode.
