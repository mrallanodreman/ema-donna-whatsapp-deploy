# Donna en Coolify (draft-only)

## Por qué no Embedded Signup

La app Meta `EMA Packaging Intelligence` (`1111727731562433`) **no es Tech Provider**.
Embedded Signup v4 exige Tech Provider, por lo que el diálogo `FB.login(config_id=...)`
termina en “Sorry, something went wrong.”
> Actualizado 2026-11-22: la app pasó a **Published** con 0 required actions. El texto
> “Unpublished” de esta sección era válido el 2026-11-21; NO volver a publicar.

El propio panel de la app indica la ruta correcta para número propio:
**Use cases → Connect on WhatsApp → Integrate with API** (no *Become a Partner*).
Pasos: test number → producción (número propio, System User, webhook, pago) → verificación Business.

## Artefactos

- `Dockerfile`: imagen `python:3.12-slim`, usuario no root, `EMA_DATA_DIR=/app/data`, `EMA_HOST=0.0.0.0`, puerto `8099`, `CMD ema watch`.
- `compose.yaml`: mismo servicio con volumen `donna-data` y healthcheck en `/health`.
- `.dockerignore`: excluye `.venv`, caches, `.env`, `data/*`.

Verificado: `46 tests` + 1 nuevo test de configuración (47 en total), build local,
`GET /health` → `{"status":"ok"}` y `GET /status` con `live=false` y todos los secretos en `false`.

## Despliegue

1. Coolify → New resource → Dockerfile (o Compose) desde este repo → rama actual.
2. Sin secretos en Git. En Coolify → Environment Variables:
   - `EMA_LIVE=false` (draft-only hasta validar token real)
   - `EMA_HOST=0.0.0.0`, `EMA_PORT=8099`, `EMA_DATA_DIR=/app/data`
   - `WA_APP_ID=1111727731562433`
   - `WA_APP_SECRET`, `WA_WEBHOOK_VERIFY_TOKEN` (usar los existentes de la app Meta)
   - `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_WABA_ID` (pendientes de Meta Business Suite)
   - `EMA_ALLOWLIST` (solo el Phone Number ID propio)
   - `META_APP_ID`, `META_APP_SECRET`, `EMA_MASTER_KEY` si se reutilizan flujos IG/Threads
3. Persistir `/app/data` (audit, idempotencia y tokens cifrados).
4. Dominio HTTPS propio en Coolify → registrar
   `GET|POST https://<dominio>/webhooks/whatsapp` en la app Meta con el verify token.
5. Suscribir el evento `messages` en WhatsApp → Configuration → Webhook.

## Puesta en vivo (solo tras validación)

- `WA_ACCESS_TOKEN` = token del System User con `whatsapp_business_management` + `whatsapp_business_messaging`.
- `EMA_ALLOWLIST` debe contener exactamente el `WA_PHONE_NUMBER_ID` propio.
- Enviar un payload firmado de prueba; confirmar que `/status` tenga
  `whatsapp_token_configured=true` y que el borrador no contenga el número completo.
- Recién entonces `EMA_LIVE=true`. El escalado automático sigue limitado a `agenda`/`venta`.

## Despliegue realizado (2026-11-21)

- Coolify: app `donna-whatsapp`, UUID `xk1cvwgoi5q0nuvhst2iht2z`, proyecto
  `EMA Packaging Staging` / entorno `production`, servidor `warmachine`.
- Fuente: repo público sanitizado `mrallanodreman/ema-donna-whatsapp-deploy`
  (solo código; sin IDs de WABA/teléfono ni notas internas). El repo privado
  `mrallanodreman/ema-donna-whatsapp` conserva el historial completo.
- Build pack `dockerfile`, puerto `8099` publicado en `192.168.1.4:8099`,
  health check HTTP `/health` (requiere `curl` en la imagen).
- Volumen persistente `xk1cvwgoi5q0nuvhst2iht2z-donna-data` montado en `/app/data`.
- Variables cargadas como `shown_once` en Coolify; `EMA_LIVE=false` y
  `WA_ACCESS_TOKEN` aún no configurado.
- Túnel Cloudflare: `donna.edgemarketing.tech` → `http://192.168.1.4:8099`.
- Verificado: challenge público 200, POST firmado con UA de Meta 200 y
  dedupe por `wamid`; `/status` muestra secretos configurados y `live=false`.
- Panel de configuración: `ema dashboard` escucha solo en `127.0.0.1:8098` y no
  se expone por el túnel; ver `docs/donna-dashboard.md`.
