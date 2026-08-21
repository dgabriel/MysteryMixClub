# Secret Rotation Policy

When and how to rotate the secrets this repo depends on — GitHub Actions
secrets and the Droplet env-file secrets described in `docs/ci-cd.md`. Filed
from Flaught finding F-004 (PR #269, MysteryMixClub-tq2a): the Groq API key
backing the `flaught` CI job was added as a GitHub Actions secret with no
rotation policy anywhere in the repo. This is a living document — update it
as secrets are added, removed, or actually rotated.

This is the routine, no-incident case. If a secret is suspected compromised
right now, that's `docs/security/breach-notification-runbook.md` → Step 1,
not this document — that runbook's rotate-everything step takes priority.

## Scope

Two secret stores, per `docs/ci-cd.md` → "Secret setup (onboarding)":

- **GitHub Actions secrets** (Settings → Secrets and variables → Actions) —
  workflow-only, never read by a running app. Currently: `GROQ_API_KEY`
  (`flaught` job's LLM provider key).
- **Droplet env-file secrets** (`/etc/mysterymixclub/{staging,prod}.env`) —
  read by the `mysterymixclub-api` systemd service at process start. See the
  table in `docs/ci-cd.md` for the current list (`SECRET_KEY`,
  `DATABASE_URL`, `RESEND_API_KEY`, Apple Music / Google OAuth credentials,
  etc.).

## When to rotate

- **Routine:** annually. Nothing here has rotated on a schedule yet — this
  policy is what starts that clock. Track the actual date in the table
  below as rotations happen.
- **Trigger-based, rotate immediately regardless of schedule:**
  - The secret appears anywhere it shouldn't have — a log line, a CI output,
    committed to git by mistake, pasted into a chat or ticket.
  - Someone with access to the secret (GitHub admin, Droplet access) leaves
    the project or their access is otherwise revoked.
  - The provider itself discloses a security incident that could have
    exposed API keys (check the provider's status/security page).
  - Any real security incident — defer to
    `breach-notification-runbook.md`, which treats rotation as step 1 of
    containment, not a follow-up.

## How to rotate — GitHub Actions secrets

1. Generate a new key at the provider's console (e.g. Groq's dashboard).
2. `gh secret set <NAME>` (or GitHub UI) — overwrites the value in place.
   No restart needed; the next workflow run picks it up automatically.
3. Confirm the new key works — watch the next PR's `flaught` job (or
   trigger one) before revoking the old key.
4. Revoke the old key at the provider's console.

## How to rotate — Droplet env-file secrets

1. Generate/obtain the new value.
2. Update `/etc/mysterymixclub/{staging,prod}.env` with the new value.
3. `sudo systemctl restart mysterymixclub-api` — settings are cached per
   process, so editing the file alone changes nothing (`docs/ci-cd.md` →
   "Adding a new secret").
4. **Never SSH into the prod Droplet yourself** to do this — it goes
   through whoever holds prod access, not an ad hoc session. Staging is
   more permissive but still worth pairing on for anything shared with prod
   (e.g. don't reuse a value across environments — `docs/ci-cd.md` already
   calls this out for `SECRET_KEY`).
5. Confirm the service came back healthy (`systemctl status
   mysterymixclub-api`, then a smoke test of whatever the secret backs)
   before considering the rotation done.

## Current secrets

| Secret | Store | Last rotated | Notes |
|---|---|---|---|
| `GROQ_API_KEY` | GitHub Actions | 2026-08-21 (initial provisioning) | `flaught` job's LLM provider key |
| `SECRET_KEY` | Droplet env (staging + prod) | unknown | JWT signing — rotating invalidates every session |
| `DATABASE_URL` | Droplet env (staging + prod) | unknown | includes the Postgres password |
| `RESEND_API_KEY` | Droplet env (staging + prod) | unknown | |
| `APPLE_MUSIC_PRIVATE_KEY` | Droplet env (staging + prod) | unknown | all-three-or-none with `APPLE_MUSIC_TEAM_ID`/`APPLE_MUSIC_KEY_ID` |
| `GOOGLE_CLIENT_SECRET` | Droplet env (staging + prod) | unknown | all-three-or-none with `GOOGLE_CLIENT_ID`/`GOOGLE_REDIRECT_URI` |
| `RESEND_WEBHOOK_SECRET` | Droplet env (prod only) | unknown | |
| `DIGITALOCEAN_ACCESS_TOKEN` | local only (`terraform apply`) | unknown | not a GitHub Actions or Droplet secret — held by whoever runs Terraform |

"Unknown" means never formally tracked before this document — not
necessarily never rotated. Fill in a real date the next time each one
actually rotates.

## Housekeeping found while writing this policy

`ANTHROPIC_API_KEY` and `OLLAMA_API_KEY` are GitHub Actions secrets left
over from earlier `flaught` LLM-provider experiments (ADR 0017/0018
iterations, before settling on Groq) — as of this policy, neither is
referenced anywhere in `.github/workflows/` or `.advreview.yml`. An unused
secret isn't a rotation problem, it's a deletion candidate: nothing to
rotate on a schedule if nothing reads it. Flagged for Dawn to delete rather
than deleted here.

## Revisit if

- A secret manager (Doppler or similar) gets adopted for the Droplet env
  files — see `project_prod-doppler-secrets-manager` memory for the prior
  deprioritized evaluation. Automated rotation reminders/expiry would
  replace the manual "annually" cadence above.
- The "unknown" last-rotated dates above stay unknown for another year —
  that's a sign this policy isn't actually being followed, not that the
  secrets don't need rotating.
