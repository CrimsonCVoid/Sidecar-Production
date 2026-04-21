# Secrets that must be rotated after the 2026-04-21 security audit

Per the audit rules of engagement, the auditor did not rotate any secret
directly. Everything below needs operator action before merging the
`security-audit-2026-04-21` branches to production.

## High priority — rotate immediately

These secrets were printed to an agent transcript during recon (the
recon agent read `.env` files while mapping the codebase). Treat them as
compromised regardless of any other context.

- **`SUPABASE_SERVICE_ROLE_KEY`** — the `sb_secret_...` value in
  `/Users/carterbrady/Mymetalrooferbackupmvp-firstcommit/.env`.
  Rotate in: Supabase dashboard → Settings → API → regenerate service_role key.
  Update: this repo's `.env` AND the `WebsiteDesign-MMR/.env.local` (same project).

- **`SUPABASE_ANON_KEY`** — the `sb_publishable_...` value (same `.env` file).
  Lower urgency (it's a public key by design) but rotate alongside
  service_role so the project rotation is clean.

- **`INTERNAL_API_KEY` / `BACKEND_API_KEY`** — shared secret between the
  Next.js proxy and the FastAPI sidecar. After Phase 4 lands, this is one
  of the two accepted auth paths, so changing it is a coordinated op
  between both repos. Rotation steps:
  1. Generate a new 32-byte hex secret: `openssl rand -hex 32`
  2. Update `.env` in this repo (`INTERNAL_API_KEY=...`)
  3. Update `.env.local` in WebsiteDesign-MMR (both `BACKEND_API_KEY` and
     `INTERNAL_API_KEY` point at the same string)
  4. Redeploy both services with zero-downtime overlap or with a planned
     maintenance window

- **`RESEND_API_KEY`** — in `WebsiteDesign-MMR/.env.local`. Rotate via
  Resend dashboard.

## Medium priority — configure before merging

- **`SUPABASE_JWT_SECRET`** — newly required by the FastAPI sidecar after
  Phase 4. Pull from Supabase dashboard → Settings → API → JWT Secret
  (under the "Legacy JWT Secret" section — Supabase is migrating to asymmetric
  keys; confirm which variant your project uses).
  Add to this repo's `.env` as `SUPABASE_JWT_SECRET=...`. Without it, all
  user-JWT requests to the sidecar get 503 "Auth not configured".

- **`PLATFORM_ADMIN_EMAILS`** — newly required by the Next.js
  `/api/admin/promo-keys/generate` fix (C-5). Add to
  `WebsiteDesign-MMR/.env.local`:
  ```
  PLATFORM_ADMIN_EMAILS=you@example.com,ops@example.com
  ```
  Without it, the route returns 503 "Admin role not configured".

## Low priority — restriction checks (no rotation required)

- **`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`** — ships to the browser by design.
  Verify HTTP-referrer restriction is set in Google Cloud Console:
  APIs & Services → Credentials → edit the key → Application restrictions
  → HTTP referrers → add your prod domain(s). If the key has no referrer
  restriction, rotate it.

- **`NEXT_PUBLIC_SUPABASE_ANON_KEY`** in WebsiteDesign-MMR — see
  `SUPABASE_ANON_KEY` above. This is the same key.

## Dead config — safe to remove

- **`DEV_BYPASS_AUTH`** / **`NEXT_PUBLIC_DEV_BYPASS_AUTH`** — confirmed
  by grep to have zero code references in WebsiteDesign-MMR. Remove from
  `.env.local` to avoid future confusion.

## Verification checklist

- [ ] `SUPABASE_SERVICE_ROLE_KEY` rotated and updated in both `.env` files.
- [ ] `INTERNAL_API_KEY` / `BACKEND_API_KEY` rotated (both copies match).
- [ ] `RESEND_API_KEY` rotated.
- [ ] `SUPABASE_JWT_SECRET` added to FastAPI `.env`; sidecar starts without warnings.
- [ ] `PLATFORM_ADMIN_EMAILS` set in Next.js `.env.local`; generate route returns 403 (not 503) for non-admins.
- [ ] Google Maps API key has a referrer restriction.
- [ ] `DEV_BYPASS_AUTH` lines removed from `.env.local`.
- [ ] `scripts/audit/test_rls.ts` run against a *staging* (not prod) Supabase and all checks PASS.
