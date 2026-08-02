variable "bucket_name" {
  type        = string
  default     = "mmc-tfstate"
  description = "DO Spaces bucket name. Shared by envs/staging + envs/prod state (distinct keys) and, later, offsite pg_dump backups (MysteryMixClub-aqz0tt)."
}

variable "region" {
  type        = string
  default     = "nyc3"
  description = "Spaces region. Spaces isn't offered in nyc1 (where the droplets live) — nyc3 is the nearest Spaces region and matches infra/terraform/README.md's recommendation."
}
