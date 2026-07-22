variable "name" {
  type        = string
  description = "Droplet name, e.g. mysterymixclub-staging."
}

variable "region" {
  type        = string
  description = "DO region slug."
  default     = "nyc1"
}

variable "image" {
  type        = string
  description = "Droplet base image slug."
  default     = "ubuntu-24-04-x64"
}

variable "size" {
  type        = string
  description = "Droplet size slug (e.g. s-1vcpu-1gb)."
}

variable "vpc_uuid" {
  type        = string
  description = "UUID of an existing VPC to place the droplet in."
}

variable "ssh_key_fingerprints" {
  type        = list(string)
  description = "Fingerprints of SSH keys already registered in the DO account."
  default     = []
}

variable "droplet_tags" {
  type        = list(string)
  description = "Tags to apply to the droplet."
  default     = []
}

variable "user_data" {
  type        = string
  description = "cloud-init user data. Empty on imported droplets (DO does not return it)."
  default     = ""
}

variable "enable_backups" {
  type        = bool
  description = "Enable DO's weekly droplet backups (adds ~20% of droplet cost)."
  default     = false
}

variable "enable_monitoring" {
  type        = bool
  description = "Install the DO metrics agent."
  default     = true
}

# --- Firewall -----------------------------------------------------------------
variable "create_firewall" {
  type        = bool
  description = "Manage a DO cloud firewall for this droplet."
  default     = false
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  description = "Source CIDRs allowed to reach SSH (22). Only used when create_firewall = true."
  default     = []
}

variable "web_allowed_cidrs" {
  type        = list(string)
  description = "Source CIDRs allowed to reach 80/443."
  default     = ["0.0.0.0/0", "::/0"]
}

# --- Reserved IP --------------------------------------------------------------
variable "create_reserved_ip" {
  type        = bool
  description = "Allocate a reserved IP and bind it to the droplet (free while attached)."
  default     = false
}

# --- DNS ----------------------------------------------------------------------
variable "domain" {
  type        = string
  description = "Existing DO-hosted domain to add app records to (zone is not managed here)."
}

variable "dns_a_names" {
  type        = set(string)
  description = "Record names to point (A) at this app, e.g. [\"staging\"] or [\"@\", \"www\"]."
  default     = []
}

variable "dns_aaaa_names" {
  type        = set(string)
  description = "Record names to point (AAAA) at this app's IPv6."
  default     = []
}

variable "dns_ttl" {
  type        = number
  description = "TTL for app DNS records."
  default     = 3600
}

# --- Monitoring alerts --------------------------------------------------------
variable "create_monitor_alerts" {
  type        = bool
  description = "Manage CPU/memory/disk alert policies for this droplet."
  default     = false
}

variable "alert_emails" {
  type        = list(string)
  description = "Email addresses to notify on alert. Required when create_monitor_alerts = true."
  default     = []
}

# --- Project ------------------------------------------------------------------
variable "project_id" {
  type        = string
  description = "If set, associate the droplet (and reserved IP) with this DO project."
  default     = ""
}
