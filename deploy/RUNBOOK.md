# Droplet Deploy Runbook — `api.mymetalroofer.net`

**Goal:** stand up the FastAPI sidecar on a single DigitalOcean droplet behind
Caddy with Let's Encrypt HTTPS, reachable from the Vercel-hosted Next.js
frontend at `https://www.mymetalroofer.net`.

**Topology after this runbook is done:**

```
Browser ──https──▶ Vercel (Next.js)
                       │
                       ├─ direct: NEXT_PUBLIC_API_URL=https://api.mymetalroofer.net
                       │  (labeler tiles, hillshade, snap preview)
                       │
                       └─ proxy:  app/api/* routes → BACKEND_API_URL
                                  with X-Internal-API-Key header
                                       │
                                       ▼
                            DigitalOcean droplet
                            ┌────────────────────────────────┐
                            │ Caddy :443 (TLS, CORS, gzip)   │
                            │   ↓                             │
                            │ uvicorn :8000 (loopback only)   │
                            │   roof_pipeline.api.main:app    │
                            └────────────────────────────────┘
```

---

## Prerequisites checklist

- [ ] Domain `mymetalroofer.net` exists and you control DNS at Porkbun
- [ ] DigitalOcean droplet exists (powered off OK — we'll boot it). Ubuntu
      22.04 or 24.04. Minimum 2 GB RAM, 2 vCPU.
- [ ] You have SSH access to the droplet (or its root password)
- [ ] You've already pushed this repo's `main` (or whatever branch you'll deploy)
      to GitHub: https://github.com/CrimsonCVoid/Mymetalrooferbackupmvp
- [ ] You've **rotated the secrets** in `ROTATE_THESE.md` — at minimum
      `SUPABASE_SERVICE_ROLE_KEY` and `INTERNAL_API_KEY`. Don't deploy with
      compromised secrets.

---

## Step 1 — Power on the droplet & note the IP

In the DigitalOcean dashboard:

1. Power on the droplet.
2. Copy its public IPv4. You'll use it in step 2 and step 4. (You also need
   it for the SSH command in step 3.)

```bash
# Locally, sanity-check it's up:
ping -c 2 <DROPLET_IP>
```

If ping fails after 60s, the droplet is still booting or has cloud-firewall
rules. Check the DigitalOcean networking tab.

---

## Step 2 — Add the Porkbun DNS A-record

Porkbun → `mymetalroofer.net` → DNS Records → Add Record:

| Field | Value                |
| ----- | -------------------- |
| Type  | A                    |
| Host  | `api`                |
| Answer | `<DROPLET_IP>`      |
| TTL   | 600                  |

Wait ~2 minutes for DNS propagation, then verify locally:

```bash
dig +short api.mymetalroofer.net
# expect: <DROPLET_IP>
```

> If `dig` returns nothing, give it another 5 minutes — Porkbun's TTL settles
> faster than 600s most of the time, but cold caches happen.

---

## Step 3 — SSH in and run the bootstrap script

```bash
# From your laptop:
ssh root@<DROPLET_IP>

# On the droplet:
mkdir -p /root/deploy
exit

# Back on your laptop, push the deploy/ folder up:
scp -r ~/Mymetalrooferbackupmvp-firstcommit/deploy/ root@<DROPLET_IP>:/root/

# SSH back in and run the bootstrap:
ssh root@<DROPLET_IP>
sudo bash /root/deploy/bootstrap.sh
```

The bootstrap script is idempotent — re-running it is safe. It will:

1. Install Python 3.11, Caddy, build deps, UFW
2. Create the `mmr` system user
3. Clone the repo to `/opt/mmr-api/app`
4. Build the venv at `/opt/mmr-api/venv`
5. Drop a `.env` template at `/opt/mmr-api/app/.env` (you fill it in next)
6. Install Caddyfile and `mmr-api.service`
7. Open UFW for 22/80/443

Expected runtime: 3–5 minutes (mostly pip install).

---

## Step 4 — Fill in `/opt/mmr-api/app/.env`

```bash
# On the droplet, as root:
sudo -u mmr nano /opt/mmr-api/app/.env
```

Required fields (all secrets — never paste these in chat or commit them):

```
SUPABASE_URL=https://psdyxmxledojrqvzmdek.supabase.co
SUPABASE_ANON_KEY=<rotated anon key from Supabase dashboard>
SUPABASE_SERVICE_ROLE_KEY=<rotated service role key>
SUPABASE_JWT_SECRET=<from Supabase dashboard → Settings → API → JWT Settings>
GOOGLE_SOLAR_API_KEY=<from Google Cloud Console>
INTERNAL_API_KEY=<openssl rand -hex 32 — must EXACTLY match Vercel's INTERNAL_API_KEY>
CORS_ORIGINS=["https://www.mymetalroofer.net","https://mymetalroofer.net","https://*.vercel.app"]
DEV_ALLOW_UNAUTH=false
```

> ⚠️  `INTERNAL_API_KEY` and Vercel's `INTERNAL_API_KEY` / `BACKEND_API_KEY`
> must be the **same string**. The Next.js proxy routes send it as
> `X-Internal-API-Key`; the sidecar's `require_principal` rejects mismatches
> with 401.

Save and exit (`Ctrl-O`, `Enter`, `Ctrl-X` in nano).

---

## Step 5 — Start the services

```bash
sudo systemctl restart mmr-api
sudo systemctl restart caddy

# Confirm they're both up:
sudo systemctl status mmr-api --no-pager
sudo systemctl status caddy --no-pager

# Tail logs while you smoke-test:
sudo journalctl -u mmr-api -f
```

If `mmr-api` fails to start, check journald — it's almost always one of:
- A missing env var (pydantic raises at startup)
- `uvicorn` can't bind 8000 (port in use — `ss -tlnp | grep 8000`)
- Python import error from a missing apt package (re-run bootstrap)

---

## Step 6 — Smoke-test from your laptop

```bash
# Should return {"status":"ok"} (the /health endpoint in roof_pipeline/api/main.py)
curl -i https://api.mymetalroofer.net/health

# First request triggers Caddy's Let's Encrypt cert provisioning.
# Expect a ~10s pause on the very first request, then sub-100ms after.
```

Successful output looks like:

```
HTTP/2 200
content-type: application/json
strict-transport-security: max-age=31536000; includeSubDomains
{"status":"ok"}
```

If you get a TLS error: Caddy couldn't reach Let's Encrypt. Check:

```bash
sudo journalctl -u caddy -n 50 --no-pager
```

Common failure: port 80 not open (Caddy needs HTTP-01 challenge). Re-run UFW:

```bash
sudo ufw status
```

---

## Step 7 — Wire Vercel → droplet

In Vercel → your project → Settings → Environment Variables, ensure these
three are set in **Production, Preview, AND Development**:

| Key                  | Value                              |
| -------------------- | ---------------------------------- |
| `BACKEND_API_URL`    | `https://api.mymetalroofer.net`    |
| `ALGORITHM_API_URL`  | `https://api.mymetalroofer.net`    |
| `NEXT_PUBLIC_API_URL`| `https://api.mymetalroofer.net`    |
| `INTERNAL_API_KEY`   | (same string as droplet's .env)    |
| `BACKEND_API_KEY`    | (same string as `INTERNAL_API_KEY`) |

> The `NEXT_PUBLIC_*` one is bundled into the browser. The other four are
> server-side and used by the Vercel proxy routes
> (`app/api/projects/[id]/straighten`, `cutsheet-data`, `pdf/proposal`, etc).

Trigger a redeploy after pasting (Vercel doesn't auto-redeploy on env
changes). Deployments → ⋯ → Redeploy.

---

## Step 8 — End-to-end verification

From the deployed Vercel URL:

1. Sign in.
2. Open a project's labeling page — the hillshade tiles should load
   (network tab: requests to `api.mymetalroofer.net/hillshade/...` return 200).
3. Click "Straighten" — the polygon should snap correctly.
4. Generate a cutsheet PDF — should download successfully.

If any step hangs at "loading" forever, the proxy chain is misconfigured.
Open the browser network tab and look for the failing request — the URL,
status, and response body will tell you which leg of the chain broke
(Vercel proxy → Caddy → uvicorn).

---

## Routine operations

**Deploying new code:**

```bash
ssh root@<DROPLET_IP>
sudo -u mmr git -C /opt/mmr-api/app pull origin main
sudo -u mmr /opt/mmr-api/venv/bin/pip install -r /opt/mmr-api/app/requirements.txt
sudo systemctl restart mmr-api
```

Or just re-run `bootstrap.sh` — it's idempotent and does the pull+restart.

**Rotating `INTERNAL_API_KEY` (zero-downtime):**

The sidecar accepts any of multiple keys if you set `INTERNAL_API_KEY` to a
comma-separated list (NOT yet implemented in `deps.py:require_principal` —
update there if you need true zero-downtime rotation). Otherwise:

1. Generate new key: `openssl rand -hex 32`
2. Set both old AND new in Vercel env (overlap window).
3. Update droplet `.env` to new key, restart `mmr-api`.
4. Remove old key from Vercel env, redeploy.

**Reading logs:**

```bash
sudo journalctl -u mmr-api -f                     # live tail
sudo journalctl -u mmr-api -n 200 --no-pager      # last 200 lines
sudo journalctl -u mmr-api --since "1 hour ago"   # last hour
sudo tail -f /var/log/caddy/api.mymetalroofer.net.log   # caddy access log
```

**Restarting after server reboot:** services are enabled at boot; nothing
to do. Confirm with `systemctl is-enabled mmr-api caddy`.

---

## Rollback

If a deploy breaks the sidecar, roll back to the previous git SHA:

```bash
ssh root@<DROPLET_IP>
sudo -u mmr git -C /opt/mmr-api/app log --oneline -10
sudo -u mmr git -C /opt/mmr-api/app reset --hard <good_sha>
sudo systemctl restart mmr-api
sudo journalctl -u mmr-api -n 50 --no-pager
```

If Caddy itself is broken (rare): `sudo systemctl restart caddy`. Caddy
keeps its previous cert in `/var/lib/caddy/.local/share/caddy/`, so a
restart never re-runs ACME against rate limits.

---

## Cost / capacity sanity-check

- Droplet: 2 GB / 2 vCPU is enough for ~5 concurrent labeler sessions doing
  cutsheet generation. Bump to 4 GB if you see OOM kills in
  `journalctl -u mmr-api | grep -i "killed\|oom"`.
- Caddy + uvicorn idle ≈ 250 MB. The labeler peak ≈ 500 MB per cutsheet
  (numpy + matplotlib).
- The `MemoryMax=3G` in the systemd unit will kill (and restart) the
  service if it runs away — adjust upward if you size up the droplet.
