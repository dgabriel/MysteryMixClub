# Bootstrap: provisions the DO Spaces bucket (+ scoped access key) used as the
# S3-compatible remote-state backend for envs/staging and envs/prod, and later
# (MysteryMixClub-aqz0tt — NOT this ticket's scope) as the destination for
# nightly offsite pg_dump backups of prod Postgres. Design rationale + cost:
# infra/terraform/README.md -> "Remote state backend".
#
# WHY THIS CONFIG STAYS ON LOCAL STATE PERMANENTLY (the one exception to the
# "no local state long-term" rule stated for every other env in this repo):
# you cannot use a Spaces bucket as the backend for the same config that
# creates that bucket — on a fresh checkout there's no bucket yet for `init`
# to talk to, and a destroy/recreate of the bucket would take out the very
# state describing it. This is the standard Terraform/OpenTofu bootstrap
# pattern: a tiny, rarely-touched, deliberately-local-state config whose only
# job is standing up the backend's own storage. Its state is small, low-churn,
# and never holds application secrets beyond the Spaces key itself — treat
# `terraform.tfstate` here like any other local secret (never commit it;
# already covered by infra/terraform/.gitignore).
#
# This bucket is the ONLY sanctioned remote-state target across staging and
# prod (see the backend blocks added to envs/staging/main.tf and
# envs/prod/main.tf) — one bucket, two state keys, so there is a single source
# of truth for "where does state live" (DRY).

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.43"
    }
  }

  # Intentionally NOT a remote backend — see comment above.
}

# Provider reads the token from the DIGITALOCEAN_TOKEN env var — never hardcode it.
provider "digitalocean" {}

resource "digitalocean_spaces_bucket" "tfstate" {
  name   = var.bucket_name
  region = var.region

  # No `acl` set -> DO's default is private. Suitable for both current use
  # (Terraform state, which can contain secrets) and the later pg_dump use
  # (MysteryMixClub-aqz0tt) as-is — no permission rework needed when that
  # ships. Deliberately no `lifecycle_rule` block either: state objects are
  # few and small (no expiry needed) and the later nightly-dump retention
  # policy belongs to that ticket, not this one — adding a rule now would
  # just be guessing at its shape.
  force_destroy = false
}

# Scoped access key for state read/write today, and pg_dump uploads later.
# `readwrite` grants Get/Put/Delete/List on this bucket only; `fullaccess`
# (bucket ACL/policy changes) is not needed for either use case.
resource "digitalocean_spaces_key" "tfstate" {
  name = "${var.bucket_name}-key"

  grant {
    bucket     = digitalocean_spaces_bucket.tfstate.name
    permission = "readwrite"
  }
}
