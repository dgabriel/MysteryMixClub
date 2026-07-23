# MysteryMixClub — Terraform

Infrastructure-as-code for the DigitalOcean droplets that host MMC. Structure:

```
infra/terraform/
  modules/droplet-app/   shared module: droplet + firewall + reserved IP + DNS + monitor alerts + project
  envs/staging/          wires the module to the *existing* staging droplet (id 577618725)
  envs/prod/             droplet-shaped prod (MYS-213/MYS-225) — NOT App Platform, applied and live
```

Both environments consume the same module; the only differences are data
(`terraform.tfvars`), never forked code. The DO API token is read from the
`DIGITALOCEAN_TOKEN` env var — it is never stored in state or tfvars.

Prod is deliberately a self-managed droplet (raw VM + Nginx + systemd + local
Postgres), the same shape as staging — **not** DO App Platform — because
`digitalocean_app` is a PaaS abstraction with no portable equivalent on another
cloud (MYS-213). `.do/app.prod.yaml` is stale reference and is not used here.

---

## Bootstrap: import existing staging (do this first)

Staging was created by hand. Bring it under state before changing anything.
**None of these have been run** — review, then run yourself with a write-scoped
token. Expect a clean `plan` (no changes) afterward; if not, reconcile tfvars to
reality, not reality to tfvars.

```bash
cd envs/staging
export DIGITALOCEAN_TOKEN=...          # write-scoped
tofu init
tofu import module.staging.digitalocean_droplet.this 577618725
tofu import 'module.staging.digitalocean_record.a["staging"]' mysterymixclub.com,1822275773
tofu plan                              # MUST show "No changes"
```

Referenced but **not** imported (managed as data sources / left alone):

- SSH key `DG Macbook Pro` (id 53065356) — `data.digitalocean_ssh_key`, read-only.
- VPC `default-nyc1` (`d89b15d3-...`) — DO's auto-created default; passed by UUID,
  not managed (the default VPC can't be destroyed and shouldn't be TF-owned).
- Project `mystery-mix-club` — the droplet is already in the account-default
  project; no `project_resources` association needed for staging.

### Import gotcha (baked into the module)

The DO API does not return `user_data` or `ssh_keys`, and returns `image` as a
numeric id, not the slug. Without protection, a post-import plan would try to
**replace the live droplet**. The module sets
`lifecycle { ignore_changes = [user_data, ssh_keys, image] }` on the droplet to
prevent that. These attributes are set at create time; changing them is a
deliberate rebuild, not an in-place edit.

---

## Staging reality (inspected 2026-07-21, read-only)

| Fact | Value |
|------|-------|
| Droplet | `mysterymixclub-staging` id 577618725, `s-1vcpu-1gb`, nyc1, Ubuntu 24.04 |
| Public IPs | v4 `67.207.81.183`, v6 `2604:a880:400:d1:0:4:96b0:f001` |
| VPC | `default-nyc1` `d89b15d3-...` (10.116.0.0/20) |
| Features | monitoring, ipv6, private_networking |
| Cloud firewall | SSH locked to admin CIDRs, 80/443 open (MYS-224, 2026-07-23) |
| Reserved IP | **none** |
| Backups / snapshots | **none** |
| Monitor alerts | **none configured** |
| DNS (app) | `staging` A → 67.207.81.183 (record 1822275773) |
| DNS (email) | Resend DKIM, SES MX/SPF, DMARC, Resend Inbound MX — now Terraform-managed in `envs/prod` (ADR 0003, MYS-242), imported rather than left hand-managed |

### Staging patterns NOT carried into prod (deliberately)

1. **No backups, no offsite copy** → total data-loss risk. Prod enables weekly
   droplet backups *and* a separate offsite `pg_dump` (see below).
2. **No reserved IP** → a rebuild changes the public IP and churns DNS. Prod
   allocates a reserved IP that apex/www point at.
3. **No monitor alerts** → failures are discovered by users. Prod adds
   CPU/memory/disk alert policies.
4. Self-signed cert + basic auth is a staging-only stopgap; prod uses a real
   Let's Encrypt cert on the apex domain (handled by certbot on-box, not TF).

---

## Prod proposal (`envs/prod`, not yet applied)

- `s-2vcpu-2gb` ($18/mo): doubles staging's RAM so the on-box `npm run build` +
  uvicorn + local Postgres don't OOM-contend. `s-1vcpu-2gb` ($12) is the budget
  floor; `s-2vcpu-4gb` ($24) is the first bump under load.
- Dedicated `mysterymixclub-prod` VPC (10.120.0.0/20), separate from staging.
- Cloud firewall: SSH only from `ssh_allowed_cidrs` (**placeholder in tfvars —
  replace with your real admin CIDR before apply**), 80/443 open.
- Reserved IP bound to the droplet; apex `@` + `www` A/AAAA point at it.
- Weekly DO droplet backups **plus** an offsite logical dump (below).
- Monitor alerts (CPU/mem/disk > 80% for 5m) → `dgabriel@gmail.com`.

### Backups: offsite `pg_dump` → DO Spaces (portable primary)

Choice: **nightly `pg_dump | gzip` → DO Spaces** as the portable primary, with
DO's weekly droplet backups as a fast bare-metal fallback.

- **Spaces** is S3-compatible → the dump restores on *any* Postgres anywhere
  (aligns with the portability-first mandate). ~$5/mo (250 GB + 1 TB transfer).
- **Droplet backups** are whole-disk, DO-proprietary — great for fast recovery,
  useless off DO. Kept only as a convenience fallback, not the source of truth.

The dump cron/systemd-timer + `s3cmd`/`aws s3` wiring is server config (Ansible /
cloud-init), tracked separately — Terraform provisions the Spaces bucket; it does
not own the dump schedule. Restore drills are a runbook item.

---

## Cost

| Item | Staging now | Prod proposed | Prod budget variant |
|------|-------------|---------------|---------------------|
| Droplet | `s-1vcpu-1gb` $6 | `s-2vcpu-2gb` $18 | `s-1vcpu-2gb` $12 |
| Droplet backups (20%) | $0 (off) | $3.60 | $2.40 |
| Reserved IP (attached) | $0 (none) | $0 | $0 |
| Spaces (offsite dumps) | $0 (none) | $5 | $5 |
| Monitoring + alerts | $0 | $0 | $0 |
| **Monthly** | **$6** | **~$26.60** | **~$19.40** |

Each droplet size includes 1 TB egress; overage is $0.01/GiB. At MMC's
friend-group scale that allowance is not a concern.

### What breaks first at 10x users

Single box: app and Postgres share RAM/CPU and one failure domain. **Memory is
the first ceiling** (Postgres shared_buffers + connections + the SPA build).
Cheapest upgrade path, in order: (1) vertical resize `s-2vcpu-4gb` $24 →
`s-4vcpu-8gb` $48 (a resize is a reboot, portability-neutral); (2) move the SPA
build off the box into CI so prod RAM serves runtime only; (3) split Postgres
onto its own droplet (still a plain VM — portable) before ever reaching for
managed Postgres, which would reintroduce the lock-in we just left.

### Tradeoffs (portability is the stated priority)

- **Cost now / at 10x:** ~$27/mo → first bump ~$33 (resize + backups), then
  ~$60 if Postgres moves to its own droplet. Modest and linear.
- **Portability:** every resource here (droplet, VPC, firewall, reserved IP,
  DNS, Spaces) has a like-for-like equivalent on any cloud; no PaaS glue. A
  provider migration is a re-provision + DNS cutover, not a rewrite.
- **Operational burden:** higher than App Platform — you own OS patching,
  Postgres ops, TLS renewal, and the deadline systemd timer. This is the
  accepted cost of portability (MYS-213).
- **If forced to pick today:** `s-2vcpu-2gb` + weekly backups + Spaces dumps.
  It's the cheapest config that is *safe* (won't OOM, has an offsite restore
  path) without gold-plating for scale MMC doesn't have.

---

## Remote state backend

State currently defaults to **local** (no backend block). For two environments
that should change — local state has no locking, is a single-laptop loss risk,
and holds secrets in plaintext (never commit it; `.gitignore` covers `*.tfstate`).

**Recommendation: DO Spaces S3-compatible backend with `use_lockfile = true`**
(Terraform ≥ 1.10 / OpenTofu ≥ 1.8 support S3-native locking — no DynamoDB
table needed). Reuses the same Spaces bucket the offsite dumps need (~$5 covers
both), keeps state on DO for now, and the S3 backend + standard state JSON is
trivially repointed at AWS S3 or self-hosted MinIO on a provider move — so it is
**not** a portability trap the way `digitalocean_app` was.

Runner-up: **Terraform Cloud free tier** — free, zero-ops, remote state +
locking + run history. State format is standard, so it is *not* a portability
risk; the tradeoff is a HashiCorp/IBM dependency and state living off DO. Fine
if you'd rather not self-manage a bucket.

Avoid: **local** as the long-term answer (no locking, loss risk, secrets on a
laptop).

Example backend block to add per env once the bucket exists (endpoints are the
nyc3 Spaces region; skip the AWS-specific validations):

```hcl
terraform {
  backend "s3" {
    endpoints                   = { s3 = "https://nyc3.digitaloceanspaces.com" }
    bucket                      = "mmc-tfstate"
    key                         = "prod/terraform.tfstate"   # or staging/...
    region                      = "us-east-1"                # ignored by Spaces, required by the backend
    use_lockfile                = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
  }
}
```

Spaces access keys go in `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars,
never in the block.
