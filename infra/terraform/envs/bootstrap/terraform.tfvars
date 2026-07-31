# Matches infra/terraform/README.md's "Remote state backend" recommendation.
# Both values equal the variable defaults; kept explicit here so this file
# reads the same way every other env's tfvars does (values are data, never
# hidden behind defaults someone has to go find).

bucket_name = "mmc-tfstate"
region      = "nyc3"
