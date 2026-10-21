# Deployment specification: sandbox → AWS

What runs in the local sandbox, what its AWS counterpart is, and what
actually has to change to get from one to the other. Porting this project
is not a single database migration — it touches the Postgres instance,
the feature store's offline and online backends, how the feature-serving
code is called at inference time, how the data pipeline runs, and the
network/security layer that doesn't exist locally at all. This document
is organized by how much work each of those actually is, not by which
component happens to be built first.

Companion document: [sql/METAMODEL.md](../sql/METAMODEL.md) specifies the
`mlgov` data model itself, which is identical in both environments. This
document is about where things run and what config differs — it does not
repeat the schema.

---

## 1. Three tiers of porting effort

### Tier 1 — shared as-is, no porting needed

These files or definitions are read identically by both environments.
Nothing in them names "local" or "AWS."

| Component | File(s) | Why it needs no change |
|---|---|---|
| Governance schema DDL | `sql/mlgov_ddl.sql` | Applied to whichever Postgres instance is given to it — local container or RDS. No environment-specific statement anywhere in the file (see `sql/METAMODEL.md` section 2). |
| Feast entity and feature-view definitions | `features/entities.py`, `features/feature_views.py` (not yet written) | Feast's design deliberately separates *what a feature is* from *where it's stored* — these files declare the former only. |
| Synthetic data generation logic | `data_generator/generate.py` | Runs as plain Python either way when generating the initial dataset; see Tier 3 for how the *pipeline that re-runs it on a schedule* differs. |
| The demo/test scripts this lab is built around | SETUP.md section 9's test plan | The point-in-time join, the stale-valuation root-cause replay, the governance gate — all exercise logic, not infrastructure, and pass or fail the same way regardless of which environment they run against. |

### Tier 2 — same tool, different backend configuration

These are genuine ports: the same tool, pointed at a different backend
through config, not a different tool or a different code path. The
porting work is changing connection settings and, for Feast, which
`OfflineStore`/`OnlineStore` class is named in `feature_store.yaml` —
Feast's plugin model is built for exactly this swap.

| Component | Local | AWS | What actually changes |
|---|---|---|---|
| Registry / governance Postgres | Container, `mlops-sandbox/compose.yml`, `localhost:5433` | RDS PostgreSQL `db.t4g.micro`, `modules/metastore` | Host, port, credentials. Same schemas (`feast`, `mlgov`), same DDL file, same table shapes. |
| Feast offline store | Local Parquet files (`data_generator/out/`) via Feast's `FileOfflineStore` | S3 + Iceberg via Feast's `offline_store: type: ...` Iceberg-compatible backend | The `offline_store` block in `feature_store.yaml` changes; the `feature_views.py` definitions do not, since they declare schema and source, not storage backend. Iceberg support in Feast's offline store may require an additional connector package — to be confirmed when this step is actually built. |
| Feast online store | SQLite (Feast's default `OnlineStore`) | DynamoDB via Feast's `DynamoDBOnlineStore` | The `online_store` block in `feature_store.yaml` changes. `feast materialize` is the same command in both environments; it writes to whichever online store is configured. |
| Feast SDK calls at inference time | `store.get_online_features(...)` called from wherever local inference testing happens | `store.get_online_features(...)` called from inside the SageMaker inference container | **The call is the same Feast Python SDK call in both environments** — confirmed against AWS's own reference implementation (see section 3). Only `feature_store.yaml`'s `online_store` config changes what it reads from underneath. |

### Tier 3 — different technology behind the same role

These are not ports. They are different systems that happen to do an
analogous job; porting from local to AWS here means building the AWS
side as its own thing, informed by what the local version proved, not
reconfiguring the local version's code to point somewhere else.

| Local | AWS | Why this is not a config change |
|---|---|---|
| MLflow, run as a container (`gunicorn`/`mlflow server` process, always running, backed by the `mlflow` Postgres database) | "Serverless MLflow," SageMaker-managed (SETUP.md section 2: free since December 2025; no server for this project to run or pay for when idle) | Locally, MLflow is a long-running service this project operates. On AWS, per SETUP.md's own architecture decision, there is deliberately no server for this project to run at all — SageMaker manages it. The local container's job is only to let you learn MLflow's tracking API and UI before that managed service is provisioned; the container itself has no AWS counterpart to "become." |
| `feast apply` / `feast materialize`, run from a custom-built CLI container (`mlops-sandbox/feast/`, not yet built) | The same commands, run from SageMaker Studio or a CI job | The commands and their effect on the registry are identical. What differs is *where they execute from* — locally, a container built for this purpose; on AWS, compute this project doesn't have to build a container image for, since SageMaker Studio and CI runners already exist as execution environments. |
| Feast's standalone `feature-server` (its official online-serving HTTP image, if used locally for learning) | Not used in production inference — confirmed against AWS's reference architecture (see section 3) | `feature-server` exists specifically for non-Python clients that can't embed Feast's SDK. A SageMaker inference container runs Python and embeds the SDK directly, so there is no role for the standalone server on the AWS side of this project at all — it is a local-only learning aid, not a component being ported. |
| The data generator, run as a one-off Python script (`data_generator/generate.py`) | AWS Glue jobs, Spark-based, scheduled by EventBridge (SETUP.md section 2, "Feature pipelines") | Glue runs Spark, not pandas. The *transformation logic* the generator encodes (how source tables become feature values) is the specification Glue jobs need to reimplement in Spark; the Python script itself does not deploy to Glue. This is new engineering, informed by the generator's logic, not a lift of the generator's code. |
| Nothing — podman-compose handles container networking implicitly (`localhost` + published ports) | VPC, subnets, security groups, IAM roles, gateway endpoints for S3/DynamoDB (SETUP.md sections 2 and 7) | There is no local equivalent to port. This is net-new AWS-side infrastructure work with no sandbox analog to draw from beyond "these are the services that need to reach each other" (RDS ↔ Glue ↔ SageMaker ↔ S3 ↔ DynamoDB). |

---

## 2. Local sandbox inventory

What actually exists in `mlops-sandbox/` right now, versus what this
document anticipates being added. Kept current as the sandbox grows — see
[PLAN.md](../PLAN.md) for the up-to-date build status; this section
should not be trusted over that one if they disagree.

| Service | Status | Image | Notes |
|---|---|---|---|
| `postgres` | Running | `docker.io/library/postgres:18-alpine` | PG18 required for native `uuidv7()`; see `sql/mlgov_ddl.sql`'s header comment. Port 5433 (controlled using .env). |
| `mlflow` | Not yet built | *(to be decided — see Tier 3 above)* | Backed by the `mlflow` database already created inside the running Postgres container. |
| `feast-cli` | Not yet built | *(custom Dockerfile — Feast publishes no official all-purpose CLI image)* | For `feast apply`, `feast materialize`, and building training sets. |
| `feature-server` | Not yet built, may not be needed | `quay.io/feastdev/feature-server` (official Feast image, confirmed to exist, tag `0.66.0` at time of writing) | Optional — see Tier 3: this image's role is serving non-Python clients, which this project's SageMaker inference path does not need. Worth standing up locally anyway, purely to see Feast's online-serving HTTP API in action while learning, with the understanding it may never be deployed on the AWS side. |

---

## 3. Verified vs. assumed

Two claims in this document were checked against primary sources rather
than assumed, because getting them wrong would have sent local learning
time toward a pattern that doesn't match how the AWS side actually needs
to work:

- **SageMaker inference code calls Feast's Python SDK directly, the same
  `get_online_features()` call used locally** — confirmed against AWS's
  own reference walkthrough, "Getting started with Feast, an open source
  feature store, running on AWS managed services"
  (aws.amazon.com/blogs/opensource), which instantiates a `FeatureStore`
  object inside the serving path and calls `get_online_features()`
  directly against DynamoDB, without going through Feast's standalone
  feature-server.
- **Feast's standalone `feature-server` HTTP image is for non-Python
  clients**, not a required piece of a Python-based SageMaker deployment —
  confirmed against Feast's own documentation for that server
  (docs.feast.dev/reference/feature-servers/python-feature-server), which
  describes it as an HTTP/JSON wrapper for clients that cannot embed the
  Python SDK.

One open question, not yet resolved: whether Feast's `FileOfflineStore` →
Iceberg-on-S3 offline store swap requires an additional connector package
beyond Feast's base install. To be confirmed when the offline-store
configuration is actually built (Tier 2, row 2).

---

## 4. Practical implication for build order

Because Tier 3 components have no local-to-AWS lift, building them
locally first (MLflow container, `feast-cli` container) is purely a
learning exercise — it de-risks understanding *how MLflow tracking and
Feast's CLI work* before writing the Terraform that provisions their AWS
equivalents, but the local container itself is not a step on the critical
path to the AWS deployment. The Tier 2 components (Postgres, Feast's
offline/online store config) are the ones where getting the local version
right directly reduces AWS-side rework, since the same `feature_views.py`
and the same `mlgov_ddl.sql` carry over unchanged — only their
`feature_store.yaml` connection block and RDS connection string need to
change.
