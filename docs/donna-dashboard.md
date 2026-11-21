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
- **Diagnóstico**: modo live/draft, firma HMAC y verify token separados para
  WhatsApp y Meta, token de envío de WhatsApp, allowlist y presencia de IDs
  WABA/teléfono.
- **Configuración total**: todos los campos de `Settings`, agrupados en
  EMA/Donna, Meta, WhatsApp Cloud API, Instagram y Threads.

Los secretos (`*_SECRET`, `*_TOKEN`, `EMA_MASTER_KEY`) **nunca** se renderizan:
aparecen como `•••••••• (configurado)` o `sin configurar`. La página no incluye
sus valores en HTML, atributos ni sugerencias.

## Qué permite editar

- Cualquier campo no secreto de `Settings`, excepto los tres protegidos.
- Campos secretos: dejar vacío = conservar el valor actual; marcar *limpiar* =
  eliminar la clave del `.env`.
- Guardado atómico del `.env` (mismo directorio, `os.replace`, `fsync`, permisos
  0600), preservando líneas y claves ajenas.
- Auditoría de cambios en `data/config-audit.jsonl` (0600): timestamp, actor,
  acción y **solo nombres de claves**, nunca valores.

`EMA_LIVE`, `WA_ACCESS_TOKEN` y `EMA_MASTER_KEY` se muestran como
**solo lectura**: el panel los consulta pero nunca acepta cambios. Cualquier
POST que intente modificarlos se ignora.

## Controles de seguridad

- Middleware que rechaza cualquier `Host` que no sea loopback (defensa contra
  DNS rebinding), cualquier `Origin` externo y cualquier cabecera
  `X-Forwarded-*` / `X-Real-IP` (un proxy que reescriba `Host` no puede activar
  el panel).
- Token CSRF por proceso, incluido en los formularios y validado en cada POST.
- Sin dependencias de `python-multipart`: se parsea solo
  `application/x-www-form-urlencoded`.
- Validación con `Settings.model_validate` **antes** de escribir: un valor
  inválido (por ejemplo `EMA_PORT=70000`) devuelve 400 y no toca el archivo.
- Se rechaza cualquier valor con expansión de variables (`$VAR`, `${VAR}`):
  python-dotenv la resolvería al cargar y podría corromper secretos.
- Los valores se leen del `.env` con `interpolate=False`: una variable del
  entorno del proceso no puede sobreponerse a lo que muestra el panel.
- Cabeceras `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer` y CSP restrictiva, también en respuestas 403.
- Sin CDN, fuentes ni scripts externos; todo el CSS/JS es local e inline.
- uvicorn con `access_log=False` para no registrar rutas ni parámetros.
- Candado async alrededor de cada escritura para no perder cambios simultáneos.

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

Cubren: secretos ausentes en HTML, rechazo de Host/Origin/cabeceras *Forwarded
ajenos, CSRF, campos protegidos de solo lectura, validación previa, rechazo de
expansión de variables, valores del entorno del proceso que no sobre escriben
al `.env`, ausencia de assets externos, limpieza de secretos, preservación de
claves desconocidas, permisos 0600 y auditoría sin valores.
