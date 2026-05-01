# SAM auto-panel service — deploy runbook

Phase 2 of the pipeline upgrade. Runs SAM ViT-H against snapshot
imagery, filters masks with the per-sample building footprint, and
writes the resulting suggestions back to `training_samples.auto_panels`.

This is a **separate** service from `mmr-api`. Different host, different
venv, different port. Do not try to mount it into the existing FastAPI
sidecar — the GPU memory profile and the Python deps don't compose.

| | mmr-api (existing) | mmr-sam (this service) |
|---|---|---|
| Host | DigitalOcean droplet `209.97.156.206` | Thunder Compute A100 `154.54.100.231` (UUID `eyulhq73`) |
| Port | 8000 | 8001 |
| Workers | 2 | 1 (model is 24 GB GPU-resident; 1 worker is correct) |
| Bind | 127.0.0.1 (Caddy in front) | 0.0.0.0 (recommended: Caddy in front; bare 8001 acceptable for MVP) |
| Auth | `X-Internal-API-Key` + Supabase JWT | `X-Internal-API-Key` only |
| Deps | `requirements.txt` | `requirements-sam.txt` |

## Deploy from scratch

You'll need:
- The Thunder Compute SSH key
- The internal API key (matches the value in the web repo's
  `INTERNAL_API_KEY` env var on Vercel)
- Supabase service-role key + URL

```bash
# ---- 1. Get on the box ------------------------------------------------
ssh ubuntu@154.54.100.231       # or whatever the VM ships with
sudo -i

# ---- 2. System user + dirs --------------------------------------------
useradd -r -m -d /opt/mmr-sam -s /bin/bash mmr || true
install -d -o mmr -g mmr -m 0755 /opt/mmr-sam/app /opt/mmr-sam/weights

# ---- 3. Code ----------------------------------------------------------
sudo -u mmr -H bash <<'EOF'
cd /opt/mmr-sam
if [ ! -d app/.git ]; then
  git clone https://github.com/CrimsonCVoid/Mymetalrooferbackupmvp.git app
fi
cd app && git fetch && git reset --hard origin/main
EOF

# ---- 4. Python venv ---------------------------------------------------
# Confirm CUDA toolkit is present:
nvidia-smi   # should print the A100 + driver
# pick a python; the Thunder image usually ships 3.10 or 3.11
sudo -u mmr -H bash <<'EOF'
cd /opt/mmr-sam
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
# torch first so the wheel matches the host CUDA; default index is fine
# on the Thunder image — if you get a CPU-only torch the segment-anything
# import works but inference falls to CPU. Override with:
#   pip install torch==2.4.0+cu121 --index-url https://download.pytorch.org/whl/cu121
pip install -r app/roof_pipeline/sam_service/requirements-sam.txt
deactivate
EOF

# ---- 5. SAM weights ---------------------------------------------------
# Public Meta release, Apache 2.0. ~2.4 GB.
sudo -u mmr -H bash <<'EOF'
cd /opt/mmr-sam/weights
curl -L -o sam_vit_h_4b8939.pth \
  https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth
sha256sum sam_vit_h_4b8939.pth
# Expected (from the segment-anything repo README):
#   a7bf3b02f3ebf1267aba913ff637d9a2d5c33d3173bb679e46d9f338c26f262e  sam_vit_h_4b8939.pth
EOF

# ---- 6. .env ----------------------------------------------------------
# Copy the template and fill values — chmod 0600 enforced.
cat > /opt/mmr-sam/app/.env <<'EOF'
# Required
SUPABASE_URL=https://psdyxmxledojrqvzmdek.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...    # service-role; never the anon key
INTERNAL_API_KEY=...             # MUST match the web repo's INTERNAL_API_KEY

# Defaults — uncomment to override
# SAM_CHECKPOINT_PATH=/opt/mmr-sam/weights/sam_vit_h_4b8939.pth
# SAM_MODEL_VERSION=sam_vit_h_4b8939
# SAM_POINTS_PER_SIDE=32
# SAM_MIN_MASK_REGION_AREA=5000
# SAM_IN_FOOTPRINT_THRESHOLD=0.80
# SAM_APPROX_EPSILON_PX=2.0
# SAM_CROP_MARGIN_PX=16
EOF
chown mmr:mmr /opt/mmr-sam/app/.env
chmod 0600 /opt/mmr-sam/app/.env

# ---- 7. Systemd unit --------------------------------------------------
cp /opt/mmr-sam/app/roof_pipeline/sam_service/systemd/mmr-sam.service \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mmr-sam
systemctl status mmr-sam     # should be "active (running)"
journalctl -u mmr-sam -n 50  # confirm "SAM ready" line on first request
```

## Sanity-check from the GPU host

```bash
# Health
curl http://127.0.0.1:8001/health

# Kick off a generation for a known sample (this triggers the model
# load on first call — subsequent calls are warm).
curl -X POST -H "X-Internal-API-Key: $INTERNAL_API_KEY" \
  http://127.0.0.1:8001/api/v2/auto-panels/99572f04-68ef-4ad5-8394-864b7b55d177
# 202 Accepted — generation runs in the background.

# Tail the logs to watch the SAM run:
journalctl -u mmr-sam -f

# After ~30-60s, query the row to see the result:
curl -s "https://psdyxmxledojrqvzmdek.supabase.co/rest/v1/training_samples?id=eq.99572f04-68ef-4ad5-8394-864b7b55d177&select=auto_panels,auto_panels_generated_at,auto_panels_model_version" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" | jq '.[0]'
```

## Sanity-check from the web side (after the v2 proxy is deployed)

```bash
# Set NEXT_PUBLIC_SAM_SERVICE_URL=https://sam.mymetalroofer.net (or
# https://154.54.100.231:8001 for direct access) on Vercel. Then:
curl -X POST https://app.mymetalroofer.net/api/v2/projects/<sample_id>/auto-panels
curl    https://app.mymetalroofer.net/api/v2/projects/<sample_id>/auto-panels
```

## Recommended hardening (do this before the service handles real users)

1. **Caddy + Let's Encrypt** in front of port 8001:
   ```caddyfile
   sam.mymetalroofer.net {
       reverse_proxy 127.0.0.1:8001
   }
   ```
   Then `ufw deny 8001/tcp` so only Caddy reaches it.
2. **Rotate `INTERNAL_API_KEY`** and put it in Vercel + this `.env` at
   the same time. Restart `mmr-sam` after rotation.
3. **CloudWatch / journald shipping** — wire `journalctl -u mmr-sam` to
   your existing log aggregator so SAM failures aren't invisible.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `503 SAM service is not configured (INTERNAL_API_KEY missing)` | `.env` not loaded | check `EnvironmentFile=` and the file's permissions |
| `401 Invalid internal API key` | header doesn't match `.env` | verify the web repo's `INTERNAL_API_KEY` matches |
| First request takes ~30s before any SAM log | model loading | expected; second request is warm |
| `auto_panels` stays null after a request | likely `no_footprint` | verify `training_samples.building_footprint_geojson` is non-null; check `journalctl -u mmr-sam` for the fallback reason |
| Inference falls to CPU + extremely slow | wrong torch wheel | `pip install torch==X.Y.Z+cu121 --index-url https://download.pytorch.org/whl/cu121` |
| OOM at model load | another GPU process is holding memory | `nvidia-smi` — kill stragglers; SAM ViT-H needs ~24 GB |
