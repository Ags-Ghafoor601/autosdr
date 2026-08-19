# Deploying AutoSDR

Three supported paths, smallest to largest.

## 1 · Public URL in 30 seconds (Cloudflare quick tunnel)

No account needed. From the repo root with the server running:

```powershell
.\scripts\tunnel.ps1
```

The script starts a Cloudflare tunnel to `localhost:8000`, prints the public
`https://….trycloudflare.com` URL, and patches `BOOKING_BASE_URL` in `.env`
(then restarts the server) so booking links inside outreach emails are
publicly clickable — a prospect can book from their phone.

## 2 · Docker (any host)

```bash
docker build -t autosdr .
docker run -p 8000:8000 --env-file .env autosdr
```

## 3 · Render (managed, free tier)

The repo ships `render.yaml`. On render.com: **New + → Blueprint → select this
repo**, fill in `OPENAI_API_KEY` and `SERPER_API_KEY`, deploy. Health check is
wired to `/api/health`. Set `BOOKING_BASE_URL` to the assigned onrender URL.

Notes for any deployment:
- SQLite lives in `data/` — mount a volume for persistence on containers.
- Live email/WhatsApp need their `.env` credentials; both default to the
  simulated channels otherwise, so a keys-only deploy still demos fully.
