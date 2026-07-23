# ADR 0003: All mysterymixclub.com email DNS records become Terraform-managed

**Status:** Accepted
**Date:** 2026-07-23

## Context

`mysterymixclub.com`'s app-facing DNS (apex/`www` A/AAAA, `staging` A) is
already Terraform-managed via `infra/terraform/envs/{prod,staging}`. The
domain's *email* records — Resend's outbound DKIM (`resend._domainkey` TXT),
the SES bounce/feedback MX and SPF (`send` MX + TXT), and `_dmarc` — were
added by hand through the Resend/DO dashboards when outbound email was first
set up, and `infra/terraform/README.md` explicitly documents this split:
"DNS (email) ... left unmanaged by TF."

MYS-242 (inbound mail forwarding to `mysterymixclubspotify@gmail.com` via
Resend Inbound) needs one new record: an MX on the apex
(`inbound-smtp.us-east-1.amazonaws.com`, priority 10) pointing receiving at
Resend. Adding just that one record by hand would have kept the existing
split intact, but it leaves the domain's email DNS half in Terraform, half
hand-managed, with no record of *why* — exactly the kind of drift an ADR
exists to prevent someone from "fixing" later by assuming it was an
oversight.

## Decision

All of `mysterymixclub.com`'s email-related DNS — the three existing
hand-added records plus the new inbound MX — moves into Terraform, in
`infra/terraform/envs/prod/main.tf` (the file that already owns the apex
domain's other records). The three existing records are imported into state
as-is, not recreated, so `tofu plan` shows zero drift for them. This
supersedes the "left unmanaged by TF" note in `infra/terraform/README.md`,
which is updated alongside this ADR.

Email DNS lives in `envs/prod`, not a separate DNS-only environment, because
the apex domain is already single-owned there (prod's `digitalocean_record.a["@"]`
etc.) — splitting domain-level records across two Terraform configs would be
a worse footgun than the split this ADR is closing.

## Consequences

- A future change to any Resend DNS record (rotating DKIM, adding a second
  receiving domain, etc.) goes through a Terraform PR like any other infra
  change, not a dashboard click — reviewable, and it shows up in `tofu plan`
  if it ever drifts from what Resend's dashboard shows.
- `infra/terraform/README.md`'s DNS table is updated to drop the "left
  unmanaged by TF" line.
- Applying `envs/prod` now requires care around these records specifically:
  changing `value`/`priority` on the imported ones would actually change
  production email delivery (SPF/DKIM break outbound auth, MX changes break
  routing) — same blast radius as always, just now something `tofu plan`
  will show explicitly instead of it being invisible to Terraform entirely.
- Does not change who *configures capabilities* on Resend's side (enabling
  the receiving capability, generating the MX value) — that still happens in
  the Resend dashboard, same as DKIM originally did. This ADR only covers
  where the resulting DNS records are declared once known.

## Revisit if

A second domain or environment needs its own independent email DNS (e.g. a
staging-only receiving address) — at that point, decide whether it still
fits in `envs/prod` or needs the separate DNS-only environment this ADR
chose not to create.
