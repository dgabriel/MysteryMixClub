locals {
  # Reserved IPs are IPv4-only on DO; apex/www A records point at the reserved IP
  # when one exists, otherwise at the droplet's ephemeral public IPv4.
  ipv4_target = var.create_reserved_ip ? digitalocean_reserved_ip.this[0].ip_address : digitalocean_droplet.this.ipv4_address
  ipv6_target = digitalocean_droplet.this.ipv6_address

  monitor_alerts = {
    cpu = {
      type        = "v1/insights/droplet/cpu"
      description = "${var.name}: CPU > 80% for 5m"
    }
    memory = {
      type        = "v1/insights/droplet/memory_utilization_percent"
      description = "${var.name}: memory > 80% for 5m"
    }
    disk = {
      type        = "v1/insights/droplet/disk_utilization_percent"
      description = "${var.name}: disk > 80% for 5m"
    }
  }
}

resource "digitalocean_droplet" "this" {
  name       = var.name
  region     = var.region
  size       = var.size
  image      = var.image
  vpc_uuid   = var.vpc_uuid
  ssh_keys   = var.ssh_key_fingerprints
  tags       = var.droplet_tags
  user_data  = var.user_data
  backups    = var.enable_backups
  monitoring = var.enable_monitoring
  ipv6       = true

  lifecycle {
    # DO's API does not return user_data or ssh_keys, and returns image as a
    # numeric id rather than the slug — so a plan against an *imported* droplet
    # would otherwise force an in-place-impossible replacement of the live box.
    # These are set at create time; changing them requires a deliberate rebuild.
    ignore_changes = [user_data, ssh_keys, image]
  }
}

resource "digitalocean_firewall" "this" {
  count = var.create_firewall ? 1 : 0

  name        = "${var.name}-fw"
  droplet_ids = [digitalocean_droplet.this.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.ssh_allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = var.web_allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = var.web_allowed_cidrs
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

resource "digitalocean_reserved_ip" "this" {
  count      = var.create_reserved_ip ? 1 : 0
  region     = var.region
  droplet_id = digitalocean_droplet.this.id
}

resource "digitalocean_record" "a" {
  for_each = var.dns_a_names

  domain = var.domain
  type   = "A"
  name   = each.value
  value  = local.ipv4_target
  ttl    = var.dns_ttl
}

resource "digitalocean_record" "aaaa" {
  for_each = var.dns_aaaa_names

  domain = var.domain
  type   = "AAAA"
  name   = each.value
  value  = local.ipv6_target
  ttl    = var.dns_ttl
}

resource "digitalocean_monitor_alert" "this" {
  for_each = var.create_monitor_alerts ? local.monitor_alerts : {}

  alerts {
    email = var.alert_emails
  }
  window      = "5m"
  type        = each.value.type
  compare     = "GreaterThan"
  value       = 80
  enabled     = true
  entities    = [tostring(digitalocean_droplet.this.id)]
  description = each.value.description
}

resource "digitalocean_project_resources" "this" {
  count = var.project_id == "" ? 0 : 1

  project = var.project_id
  resources = concat(
    [digitalocean_droplet.this.urn],
    var.create_reserved_ip ? [digitalocean_reserved_ip.this[0].urn] : [],
  )
}
