# PROPOSED prod config — a droplet-shaped prod per MYS-213 (NOT App Platform).
# This is a design proposal for review, not yet applied. Sizing/backup choices
# and their tradeoffs are documented in infra/terraform/README.md.

droplet_name = "mysterymixclub-prod"
region       = "nyc1"

# 2 vCPU / 2 GB / 60 GB, $18/mo. Doubles staging's RAM so the on-box npm build +
# uvicorn + local Postgres don't contend for memory. s-1vcpu-2gb ($12) is the
# budget floor; s-2vcpu-4gb ($24) is the first vertical bump under load.
droplet_size = "s-2vcpu-2gb"
image        = "ubuntu-24-04-x64"

# Dedicated prod VPC range (distinct from staging's default-nyc1 10.116.0.0/20).
vpc_ip_range = "10.120.0.0/20"

droplet_tags = ["prod", "mysterymixclub"]

enable_backups = true # ~$3.60/mo (20% of $18). Fast full-box recovery.

# REPLACE with your real admin IP(s) before apply. 0.0.0.0/0 here would recreate
# staging's mistake of exposing SSH to the whole internet.
ssh_allowed_cidrs = ["203.0.113.0/32"] # placeholder — Dawn's admin IP/CIDR

domain         = "mysterymixclub.com"
dns_a_names    = ["@", "www"] # apex + www (ties to MYS-174 domain migration)
dns_aaaa_names = ["@", "www"]
dns_ttl        = 3600

alert_emails = ["dgabriel@gmail.com"]
