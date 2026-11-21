# Donna — consola local de configuración

Panel de configuración **solo local**. No se monta en el servidor de webhooks ni
se publica por el túnel de Cloudflare: es un proceso independiente que escucha en
`127.0.0.1` y se abre desde la propia máquina.

```bash
cd /mnt/sda1/EdgeMarketing/ema-ig-threads
.venv/bin/ema dashboard                 # http://127.0.0.1:8098
.venv/bin/ema dashboard --port 8099 --env-file /ruta/a/otro.env
```

`--host` solo acepta `127.0.0.1`, `localhost` o `::1`; cualquier otro valor
termina el proceso con error.

## Qué muestra

- **Perfil personal**: nombre, rol, zona horaria y notas del operador
  (`data/donna-profile.json`, 0600).
- **Diagnóstico**: modo live/draft, firma HMAC, verify token, token de envío de
  WhatsApp, allowlist y presencia de IDs WABA/teléfono.
- **Configuración total**: todos los campos de `Settings`, agrupados en
  EMA/Donna, Meta, WhatsApp Cloud API, Instagram y Threads.

Los secretos (`*_SECRET`, `*_TOKEN`, `EMA_MASTER_KEY`) **nunca** se renderizan:
aparecen como `•••••••• (configurado)` o `sin configurar`. La página no incluye
sus valores en HTML, atributos ni sugerencias.

## Qué permite editar

- Cualquier campo no secreto de `Settings`.
- Campos secretos: dejar vacío = conservar el valor actual; marcar *limpiar* =
  eliminar la clave del `.env`.
- Guardado atómico del `.env` (mismo directorio, `os.replace`, permisos 0600),
  preservando líneas y claves ajenas.
- Auditoría de cambios en `data/config-audit.jsonl` (0600): timestamp, actor,
  acción y **solo nombres de claves**, nunca valores.

## Controles de seguridad

- Middleware que rechaza cualquier `Host` que no sea loopback (defensa contra
  DNS rebinding) y cualquier `Origin` externo.
- Token CSRF por proceso, incluido en los formularios y validado en cada POST.
- Sin dependencias de `python-multipart`: se parsea solo
  `application/x-www-form-urlencoded`.
- Cabeceras `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer` y CSP restrictiva.
- Sin CDN, fuentes ni scripts externos; todo el CSS/JS es local e inline.
- uvicorn con `access_log=False` para no registrar rutas ni parámetros.

## Alcance

El panel edita el `.env` **local**. La app desplegada en Coolify mantiene sus
variables en el contenedor (`xk1cvwgoi5q0nuvhst2iht2z`) y no se ven afectadas
por este panel. Si se necesita inspeccionar un volcado de esas variables,
exportarlas a un archivo local y pasar `--env-file` (sin imprimir secretos).

`EMA_LIVE=true` y un `WA_ACCESS_TOKEN` real siguen estando fuera del panel:
solo se activan tras validar webhook firmado, guardrails, permisos y token de
System User.

## Pruebas

```bash
.venv/bin/python -m pytest tests/test_dashboard.py -q
```

Cubren: secretos ausentes en HTML, rechazo de Host/Origin ajenos, CSRF,
preservación de claves desconocidas, permisos 0600 y auditoría sin valores.
