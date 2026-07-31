output "bucket_name" {
  value       = digitalocean_spaces_bucket.tfstate.name
  description = "Use as the `bucket` value in the backend \"s3\" block for envs/staging and envs/prod."
}

output "bucket_endpoint" {
  value       = digitalocean_spaces_bucket.tfstate.endpoint
  description = "Reference only — the backend blocks hardcode endpoints.s3, they don't consume this output (backend config can't reference other resources)."
}

output "access_key_id" {
  value       = digitalocean_spaces_key.tfstate.access_key
  sensitive   = true
  description = "Set as AWS_ACCESS_KEY_ID before running `tofu init -migrate-state` in envs/staging and envs/prod. Never commit or print this value."
}

output "secret_access_key" {
  value       = digitalocean_spaces_key.tfstate.secret_key
  sensitive   = true
  description = "Set as AWS_SECRET_ACCESS_KEY alongside access_key_id. Never commit or print this value."
}
