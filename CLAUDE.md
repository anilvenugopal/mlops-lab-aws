# PremiumIQ ML Platform Lab

AWS lab demonstrating a governed ML platform for P&C insurance.
Region us-east-1. Target cost under $50/month.

## Rules

- NEVER run `terraform apply` without showing me `terraform plan` output first.
- NEVER create: NAT gateways, MSK clusters, real-time SageMaker endpoints,
  provisioned MLflow tracking servers, Glue crawlers. All are cost traps.
  Explain the alternative instead.
- Glue jobs: always 2 DPU. The console default of 10 is 5x the cost.
- Every CloudWatch log group gets `retention_in_days = 7` at creation.
- SageMaker inference is ALWAYS serverless, never a real-time endpoint.
- Tag every resource `Project = piq-mlplatform`.

## Conventions

- Terraform >= 1.11, AWS provider ~> 5.70
- Modules in `modules/`, environments in `envs/`
- Resource names: `piq-<env>-<purpose>` e.g. `piq-lab-feature-store`
- Variables for anything that differs between lab and production
- Run `terraform fmt` before committing

## Architecture

Offline feature store: Iceberg on S3, append-only, nulls preserved.
Online feature store: DynamoDB on-demand, current value per entity.
Registry: Feast on RDS PostgreSQL, schema `feast`.
Governance metamodel: same instance, schema `mlgov`, no FKs across the boundary.

## When I ask for something expensive

Tell me the monthly cost before writing the code.
