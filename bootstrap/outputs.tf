output "state_bucket" {
  description = "Put this in envs/lab/backend.tf"
  value       = aws_s3_bucket.tfstate.id
}
