# Project plan and status

A living tracker for this repo — what's built, what's running, what's next.
`SETUP.md` is the reference guide (architecture, AWS setup, cost plan);
this file is the current state and the working task list. Update it as
work happens rather than letting it drift from reality.

Last updated: 2026-09-30.

---

## Where things actually stand

### AWS
- Account set up under the "new AWS experience" (project "Future Unicorn" /
  "ML Lab"), Paid Plan, $100 spend limit with all three early cost controls
  enabled. Region fixed to `us-east-2` (not `us-east-1` as SETUP.md's text
  assumes — SETUP.md itself is unchanged; the actual Terraform files use
  `us-east-2`).
- `aws sso`-style login via `aws login`, CLI profile `default`. Credentials
  are short-lived; if Terraform says "no valid credential sources," re-run
  `aws configure export-credentials --profile default --format env` and
  eval the output before the next `terraform plan`/`apply`.
- `bootstrap/` has been applied for real: the Terraform state bucket
  `piq-mlplatform-tfstate-eb27dc12` exists in AWS right now (5 resources:
  the bucket plus its versioning/encryption/public-access-block config).
  This is the only AWS infrastructure that has actually been created so far.
- `envs/lab/` is NOT initialized and has never been planned or applied. Its
  `backend.tf` already points at the real state bucket above. It cannot
  succeed yet regardless — `main.tf` references five modules
  (`storage`, `catalog`, `online_store`, `metastore`, `observability`) that
  are currently just empty directories with a README each.

### Local sandbox (`mlops-sandbox/`)
- Runs under **podman**, not Docker (Docker is also installed on this
  machine but unused here). `podman-compose` reads `compose.yml`.
- Postgres 18 (`docker.io/library/postgres:18-alpine`) is running right
  now as container `mlplatform-postgres`, healthy, on `localhost:5433`
  (not 5432 — that port is already used by a native Postgres install on
  this machine, left untouched). Config lives in `mlops-sandbox/.env`
  (gitignored; `.env.example` is the committed template).
- On first startup, `mlops-sandbox/postgres-init/01-bootstrap.sh` created
  the `feast` and `mlgov` schemas inside database `mlplatform`, applied
  `sql/mlgov_ddl.sql` in full (17 tables + 2 views, verified via `\dt`),
  and created a separate `mlflow` database on the same server. Confirmed
  working end to end.
- **Not yet built:** MLflow container, Feast container (needs a
  custom-built image — Feast has no official all-purpose CLI image, only
  an online-serving `feature-server` image), and the `feast/` config
  files that would let Feast actually register anything.
- Known environment quirk: this WSL instance's systemd user session was
  broken for most of this project (blocked multi-container networking)
  and required a full `wsl --shutdown` + reopen to fix. It's fixed now.
  If multi-container networking ever fails again with a `dbus`/`systemd
  user session` error, that's the symptom to look for.

### Data
- `data_generator/generate.py` is written, tested, and its
  point-in-time-label bug (labels dated past the dataset's own `end_date`)
  is fixed and verified. Running it writes ~20MB of Parquet to
  `data_generator/out/` (gitignored, not currently present on disk —
  regenerate with `python generate.py --config config.yaml` inside the
  venv at `data_generator/.venv/`).
- `data_generator/DATA_DICTIONARY.md` documents every column of every
  table, organized by role (reference/dimension, input, ground truth,
  operational record, feedback) rather than just an alphabetical dump.

### Governance schema (`sql/mlgov_ddl.sql`)
- Written, tested against a live PG18 container, and currently loaded
  into the running sandbox Postgres (see above). Not yet applied to any
  AWS RDS instance (there isn't one yet).
- Design lineage: a hand-picked, small subset of table shapes and naming
  conventions borrowed from the Verity governance platform
  (`github.com/anilvenugopal/verity`, `specs/schema/`), adapted to this
  lab's scale. See the file's own header comment for exactly what was
  borrowed vs. designed fresh, and `sql/METAMODEL.md` for the full
  table-by-table specification (ER diagram, every column, the key
  strategy, and a worked promotion-sequence example).
- Deliberately kind-agnostic naming (`model`, `model_version`) so a future
  non-`trained_ml` model kind (e.g. an LLM-backed model, or TypeSafe AI's
  JEV) can register without a rename — see the `model` table's comment.
- External-system pointers (a SageMaker model package ARN, a SageMaker
  endpoint name, a Feast Feature Service name) are held via a generic
  `external_reference` table rather than denormalized columns, so `mlgov`
  never becomes a second, driftable copy of facts SageMaker or Feast
  already own.

### Features (`features/`)
- Empty except for a placeholder. No `feature_store.yaml`, `entities.py`,
  or `feature_views.py` exist yet.

---

## Next steps

Roughly in dependency order — each depends on the one above it being done.

1. ~~Write `sql/METAMODEL.md`~~ — done. Full table-by-table specification,
   ER diagram, key strategy, worked promotion-sequence example.
2. ~~Write `mlops-sandbox/DEPLOYMENT.md`~~ — done. Covers the full
   sandbox, not just Postgres: three effort tiers (shared as-is / same
   tool different backend / different technology same role), with
   MLflow-container-vs-serverless-MLflow and Feast's-own-server-vs-
   SageMaker-calling-the-SDK-directly both worked out and source-checked
   rather than assumed.
3. **Add MLflow to `compose.yml`** — a second service, backed by the
   `mlflow` database that already exists in the running Postgres container.
4. **Build the Feast pieces**:
   - `features/feature_store.yaml`, `features/entities.py`,
     `features/feature_views.py` — the real Feast definitions, usable by
     both local and AWS (only the connection config in
     `feature_store.yaml` differs by environment).
   - `mlops-sandbox/feast/Dockerfile` — a small custom image (Python +
     `pip install feast`) for running `feast apply` / `materialize` /
     building training sets, since no official image covers this.
   - Add both a `feast-cli` service (our custom image) and, once
     something is actually being served, a `feature-server` service
     (Feast's official online-serving image) to `compose.yml`.
5. **Run the data generator**, register its output tables as Feast data
   sources, `feast apply`, materialize the online store, and confirm a
   `get_online_features` call round-trips correctly — the first real
   end-to-end proof the sandbox works.
6. **Build the five empty Terraform modules** (`storage`, `catalog`,
   `online_store`, `metastore`, `observability`) so `envs/lab` can
   actually plan/apply. Do this only after the local sandbox has proven
   out the Feast/mlgov design — the point of the sandbox is to avoid
   redesigning this twice.
7. **`envs/lab` first apply** — after modules exist, run `terraform plan`
   (show it before ever running `apply`, per `CLAUDE.md`'s rule) against
   the real AWS project.

---

## Open decisions parked, not yet resolved

- Whether `feature_store.yaml` should be one file with environment
  overrides, or two files (local/AWS) — flagged during the sandbox design
  discussion, not yet decided.
- SETUP.md's own text still says region `us-east-1` in prose; the actual
  Terraform files correctly say `us-east-2`. Not reconciled — SETUP.md is
  being left as the original reference document rather than rewritten.
