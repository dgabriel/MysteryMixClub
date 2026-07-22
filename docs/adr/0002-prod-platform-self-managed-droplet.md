# ADR 0002: Production moves off DO App Platform onto a self-managed droplet

**Status:** Accepted
**Date:** 2026-07-21 (decision), updated 2026-07-22 (execution ownership)

## Context

Production does not exist yet — this is a first-time build, not a migration of
live prod data. The technical design and `docs/ci-cd.md` originally specced
prod on DigitalOcean App Platform (`mysterymixclub-prod`: api service + static
site + managed Postgres 15, driven by `.do/app.prod.yaml` and
`deploy-prod.yml`). Staging already runs on a different, self-managed pattern
— a $6/mo Ubuntu Droplet with Nginx + systemd + local Postgres (MYS-39) — a
deliberate divergence made early for cost reasons.

While prepping the `www.mysterymixclub.com` cutover (MYS-174), the App
Platform choice for prod was reconsidered. Priced head to head, App Platform
(api + managed Postgres + static site, ≈$20–23/mo) and an equivalent
self-managed droplet (sized for real traffic + self-managed backups,
≈$17–23/mo) come out roughly even — cost is not the deciding factor.

The actual problem is portability: `digitalocean_app` is a DO-specific PaaS
abstraction with no equivalent resource type on any other cloud. Terraform
doesn't provide an exit ramp from that — the resource types themselves don't
translate, so infrastructure-as-code against App Platform is still a
single-vendor dead end. A droplet (raw VM + Nginx + systemd + Postgres) is the
boring, genuinely portable pattern already proven on staging, and it survives
a future provider change.

## Decision

Production will be a self-managed DigitalOcean droplet — same shape as
staging (Nginx + systemd + local Postgres) — not DO App Platform.
`.do/app.prod.yaml` and the `mysterymixclub-prod` App Platform app are retired
as the prod target; `.do/app.prod.yaml` is kept only as historical reference,
the same treatment already given to `.do/app.staging.yaml` after MYS-39.

This decision covers both the provisioning layer and the deploy pipeline:

- **Infrastructure:** Terraform under `infra/terraform/envs/prod/` (shared
  `modules/droplet-app` with staging) provisions the droplet, firewall,
  reserved IP, DNS, and monitor alerts. Design and cost detail in
  `infra/terraform/README.md`. Tracked as MYS-225.
- **CI/CD:** `deploy-prod.yml` moves from an `app_action/deploy` step to an
  SSH-based deploy running a new `scripts/deploy-prod.sh`, mirroring
  `deploy-staging.yml`. `PROD_HOST` / `PROD_SSH_USER` / `PROD_SSH_KEY` secrets
  replace `DIGITALOCEAN_ACCESS_TOKEN` as the deploy-time credential (a
  write-scoped DO token may still be needed separately for `terraform apply`).
  The `production` GitHub environment approval gate is unchanged — only what
  happens inside the gated job changes.
- **Scheduled jobs:** the `advance_mixes` deadline job runs on prod via the
  same systemd-timer pattern staging already uses
  (`mysterymixclub-advance-mixes.timer`), closing the gap `docs/ci-cd.md`
  currently flags ("prod has no systemd, deadline job not yet wired" — an
  App Platform **Job** component is no longer needed).
- **Secrets:** prod secret onboarding moves from the App Platform
  `envs:`/dashboard route to the Droplet's `/etc/mysterymixclub/*.env` +
  `systemctl restart` route — the same route staging already uses.
  `docs/ci-cd.md`'s "Adding a new secret" routine needs updating once this
  ships.

**Note on execution ownership:** this decision was originally recorded
2026-07-21 (logged on MYS-213) with the droplet provisioned and operated by
hand, explicitly outside Claude Code automation — the objection at the time
was to `digitalocean_app`/App Platform specifically, but it was stated broadly
enough to also rule out Claude building the droplet path. Revisited the next
day (2026-07-22): Claude Code will build both the Terraform and the CI/CD
migration described above. The portability objection was always to App
Platform as a target, not to IaC/automation as a method.

## Consequences

- Prod's CI/CD topology now matches staging's shape (SSH + script + systemd)
  — one deploy pattern for both environments, simpler mental model — but prod
  does **not** inherit staging's current gaps for free. Staging's missing
  firewall (MYS-224), missing backups (MYS-226), and missing monitor alerts
  (MYS-227) must each be built for prod's droplet directly; they are separate
  tickets, not automatic.
- `.do/app.prod.yaml` and the App Platform deploy path become dead once the
  droplet path ships and should be deleted outright at that point, not left
  as a reference fallback, unless a specific reason to keep it emerges.
- Losing DO App Platform's managed Postgres means backup/HA is entirely our
  responsibility going forward (MYS-226 already tracks the offsite `pg_dump`
  + restore drill this requires).
- `docs/ci-cd.md` and `docs/technical/technical-design.md` (§3 stack table,
  "Hosting: DigitalOcean App Platform") will need updating to describe the
  droplet as prod's actual target once MYS-225 ships — not done as part of
  this ADR.

## Revisit if

Traffic or operational burden outgrows what a single droplet can reasonably
carry, and horizontal scaling or a managed service becomes worth trading
portability for again — at that point, evaluate fresh rather than assuming
this decision still holds.
