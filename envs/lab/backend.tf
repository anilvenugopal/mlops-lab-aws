terraform {
  backend "s3" {
    bucket       = "piq-mlplatform-tfstate-eb27dc12"
    key          = "lab/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true    # native S3 locking, Terraform 1.11+. No DynamoDB table needed.
  }
}
