terraform {
  required_version = ">= 1.10.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.43"
    }
  }

  # Remote state (MysteryMixClub-mpxwcs). Bucket provisioned by the one-off,
  # permanently-local-state config in envs/bootstrap (see its main.tf for why).
  # Spaces access keys come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env
  # vars — never hardcoded here. Distinct `key` per env so staging + prod share
  # one bucket without colliding.
  backend "s3" {
    endpoints                   = { s3 = "https://nyc3.digitaloceanspaces.com" }
    bucket                      = "mmc-tfstate"
    key                         = "staging/terraform.tfstate"
    region                      = "us-east-1" # ignored by Spaces, required by the backend
    use_lockfile                = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
  }
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

  # MYS-224: SSH was reachable from 0.0.0.0/0 at the network edge. Firewall
  # added to lock SSH to admin CIDRs; reserved IP stays prod-only (see README).
  create_firewall    = true
  ssh_allowed_cidrs  = var.ssh_allowed_cidrs
  create_reserved_ip = false

  domain      = var.domain
  dns_a_names = var.dns_a_names
  dns_ttl     = var.dns_ttl

  create_monitor_alerts = false
}
