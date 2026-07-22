terraform {
  required_version = ">= 1.10.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.43"
    }
  }

  # State backend is intentionally unset for now (defaults to local). See
  # infra/terraform/README once a Spaces backend is provisioned (candidate ticket).
}

# Provider reads the token from the DIGITALOCEAN_TOKEN env var — never hardcode it.
provider "digitalocean" {}

# Pre-existing account resources referenced (not managed) by this stack.
data "digitalocean_ssh_key" "dg_macbook" {
  name = "DG Macbook Pro"
}

module "staging" {
  source = "../../modules/droplet-app"

  name     = var.droplet_name
  region   = var.region
  size     = var.droplet_size
  image    = var.image
  vpc_uuid = var.vpc_uuid

  ssh_key_fingerprints = [data.digitalocean_ssh_key.dg_macbook.fingerprint]
  droplet_tags         = var.droplet_tags
  enable_backups       = var.enable_backups
  enable_monitoring    = var.enable_monitoring

  # Staging today has NO cloud firewall and NO reserved IP — matched here so a
  # post-import plan is clean. See README for why these are prod-only.
  create_firewall    = false
  create_reserved_ip = false

  domain      = var.domain
  dns_a_names = var.dns_a_names
  dns_ttl     = var.dns_ttl

  create_monitor_alerts = false
}
