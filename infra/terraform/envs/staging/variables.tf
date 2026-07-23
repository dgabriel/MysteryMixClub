variable "droplet_name" { type = string }
variable "region" { type = string }
variable "droplet_size" { type = string }
variable "image" { type = string }
variable "vpc_uuid" { type = string }
variable "droplet_tags" { type = list(string) }
variable "enable_backups" { type = bool }
variable "enable_monitoring" { type = bool }
variable "domain" { type = string }
variable "dns_a_names" { type = set(string) }
variable "dns_ttl" { type = number }

variable "ssh_allowed_cidrs" {
  type        = list(string)
  description = "Source CIDRs allowed to reach SSH (22)."
}
