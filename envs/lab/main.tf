terraform {
  required_version = ">= 1.11"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.70" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "piq-mlplatform"
      ManagedBy = "terraform"
      Env       = var.env
    }
  }
}

module "storage" {
  source = "../../modules/storage"
  env    = var.env
}

module "catalog" {
  source     = "../../modules/catalog"
  env        = var.env
  bucket_arn = module.storage.feature_store_bucket_arn
}

module "online_store" {
  source = "../../modules/online_store"
  env    = var.env
}

module "metastore" {
  source         = "../../modules/metastore"
  env            = var.env
  instance_class = var.db_instance_class
}

module "observability" {
  source             = "../../modules/observability"
  env                = var.env
  monthly_budget_usd = var.monthly_budget_usd
  alert_email        = var.alert_email
}
