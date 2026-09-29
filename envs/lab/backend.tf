terraform {
  backend "s3" {
    bucket       = "piq-mlplatform-tfstate-XXXXXXXX"  # <- paste the output here
    key          = "lab/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true    # native S3 locking, Terraform 1.11+. No DynamoDB table needed.
  }
}
