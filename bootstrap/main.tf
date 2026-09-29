terraform {
  required_version = ">= 1.11"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "piq-mlplatform"
      ManagedBy = "terraform"
      Env       = "bootstrap"
    }
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

# S3 bucket names are globally unique across all AWS customers,
# hence the random suffix.
resource "aws_s3_bucket" "tfstate" {
  bucket = "piq-mlplatform-tfstate-${random_id.suffix.hex}"
}

# Versioning lets you recover a state file you corrupted.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
