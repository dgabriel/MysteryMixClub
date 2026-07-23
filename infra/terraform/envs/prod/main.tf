terraform {
  required_version = ">= 1.10.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.43"
    }
  }
}

provider "digitalocean" {}

data "digitalocean_ssh_key" "dg_macbook" {
  name = "DG Macbook Pro"
}

# Dedicated prod VPC — network isolation from staging. Portable concept (every
# cloud has an equivalent), no PaaS lock-in.
resource "digitalocean_vpc" "prod" {
  name     = "mysterymixclub-prod"
  region   = var.region
  ip_range = var.vpc_ip_range
}

module "prod" {
  source = "../../modules/droplet-app"

  name     = var.droplet_name
  region   = var.region
  size     = var.droplet_size
  image    = var.image
  vpc_uuid = digitalocean_vpc.prod.id

  ssh_key_fingerprints = [data.digitalocean_ssh_key.dg_macbook.fingerprint]
  droplet_tags         = var.droplet_tags
  enable_backups       = var.enable_backups # weekly DO backups, ~20% of droplet cost
  enable_monitoring    = true

  # Hardening staging lacks: restrict SSH to admin CIDRs, open only 80/443 to the world.
  create_firewall   = true
  ssh_allowed_cidrs = var.ssh_allowed_cidrs
  web_allowed_cidrs = ["0.0.0.0/0", "::/0"]

  # Stable public IP so apex/www DNS survives a droplet rebuild.
  create_reserved_ip = true

  domain         = var.domain
  dns_a_names    = var.dns_a_names    # ["@", "www"]
  dns_aaaa_names = var.dns_aaaa_names # ["@", "www"]
  dns_ttl        = var.dns_ttl

  create_monitor_alerts = true
  alert_emails          = var.alert_emails
}

# Email DNS (ADR 0003) — previously hand-added via the Resend/DO dashboards,
# now imported so the apex domain's email routing lives in code like every
# other record here. Changing value/priority on any of these is a real
# production email change (SPF/DKIM/MX), not a cosmetic edit.

# Resend outbound DKIM signing key.
resource "digitalocean_record" "txt_resend_dkim" {
  domain = var.domain
  type   = "TXT"
  name   = "resend._domainkey"
  value  = "p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+EGvaMbPq0oBhCay/V0fXm8jmLngcMaz3XYZVIILc497zgGVUrblorx9UCjohiNgf5Lhg1u6HKvXOj3r6kBynOKv4b3RdyV2DdhjMB2go6xV+IeF9bYFfQOrAMIoNY7RZjt7XIrZSX22Cx5O2G2m9jwj0fwyN5GONkSVLWLmhiwIDAQAB"
  ttl    = var.dns_ttl
}

# Resend/SES outbound bounce + feedback tracking (not a receiving MX).
resource "digitalocean_record" "mx_send" {
  domain   = var.domain
  type     = "MX"
  name     = "send"
  value    = "feedback-smtp.us-east-1.amazonses.com."
  priority = 10
  ttl      = 14400 # matches the record's actual TTL as set outside TF originally
}

resource "digitalocean_record" "txt_send_spf" {
  domain = var.domain
  type   = "TXT"
  name   = "send"
  value  = "v=spf1 include:amazonses.com ~all"
  ttl    = var.dns_ttl
}

resource "digitalocean_record" "txt_dmarc" {
  domain = var.domain
  type   = "TXT"
  name   = "_dmarc"
  value  = "v=DMARC1; p=none;"
  ttl    = var.dns_ttl
}

# Resend Inbound (MYS-242) — routes every address at the apex domain to
# Resend's inbound webhook pipeline; the backend relays to
# mysterymixclubspotify@gmail.com. Apex, not a subdomain, is deliberate: the
# goal is catching [anything]@mysterymixclub.com, and the apex carried no
# prior MX record, so there's no conflict to avoid (Resend's own docs warn
# to use a subdomain only when one would otherwise collide).
resource "digitalocean_record" "mx_inbound" {
  domain   = var.domain
  type     = "MX"
  name     = "@"
  value    = "inbound-smtp.us-east-1.amazonaws.com."
  priority = 10
  ttl      = var.dns_ttl
}
