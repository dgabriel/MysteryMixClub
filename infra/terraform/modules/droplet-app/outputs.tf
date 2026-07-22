output "droplet_id" {
  value       = digitalocean_droplet.this.id
  description = "Numeric droplet ID."
}

output "droplet_urn" {
  value       = digitalocean_droplet.this.urn
  description = "Droplet URN (for project association / other refs)."
}

output "public_ipv4" {
  value       = digitalocean_droplet.this.ipv4_address
  description = "Ephemeral public IPv4 of the droplet."
}

output "public_ipv6" {
  value       = digitalocean_droplet.this.ipv6_address
  description = "Public IPv6 of the droplet."
}

output "reserved_ipv4" {
  value       = var.create_reserved_ip ? digitalocean_reserved_ip.this[0].ip_address : null
  description = "Reserved IPv4 if one was allocated, else null."
}

output "dns_target_ipv4" {
  value       = local.ipv4_target
  description = "The IPv4 the app A records resolve to."
}
