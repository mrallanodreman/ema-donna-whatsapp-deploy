# Donna — WhatsApp Cloud API webhook

Draft-only service for Edge Marketing. Validates Meta webhook signatures, deduplicates
`wamid` events and produces reply drafts; automatic sending stays disabled until
`EMA_LIVE=true` and a real System User token is configured.

## Runtime

- Python 3.12, FastAPI/Uvicorn
- `GET /health`, `GET /status`, `GET|POST /webhooks/whatsapp`
- `EMA_DATA_DIR=/app/data` (persistent volume for audit/idempotency)
- Port `8099`
