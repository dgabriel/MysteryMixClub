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
