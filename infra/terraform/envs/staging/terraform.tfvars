# Values below mirror the *actual* running staging droplet (id 577618725) as
# inspected 2026-07-21. Do not change these before importing — they exist so the
# first `terraform plan` after import reports no changes.

droplet_name = "mysterymixclub-staging"
region       = "nyc1"
droplet_size = "s-1vcpu-1gb" # $6/mo, 1 vCPU / 1 GB / 25 GB
image        = "ubuntu-24-04-x64"
vpc_uuid     = "d89b15d3-73a8-4daf-bec3-ca7e30e4797b" # default-nyc1

# Droplet currently carries no user tags; monitoring + private networking + ipv6
# are droplet *features*, managed via the resource args (monitoring/ipv6), not tags.
droplet_tags = []

enable_backups    = false # no droplet backups configured today
enable_monitoring = true  # metrics agent present

domain      = "mysterymixclub.com"
dns_a_names = ["staging"] # existing record id 1822275773 -> 67.207.81.183
dns_ttl     = 3600

# Dawn's admin machine — same CIDR used for prod's firewall (confirmed 2026-07-22).
ssh_allowed_cidrs = ["141.157.247.49/32"]
