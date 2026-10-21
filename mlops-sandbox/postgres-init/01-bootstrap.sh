#!/bin/sh
# Runs once, on first container startup, via postgres's
# /docker-entrypoint-initdb.d mechanism. Creates the two schemas, applies
# the shared DDL from sql/mlgov_ddl.sql, and creates a separate database
# for MLflow's own backend store.
#
# sql/mlgov_ddl.sql is mounted into this container from the repo root (see
# compose.yml) and is not copied — the same file applies to AWS RDS later.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE SCHEMA IF NOT EXISTS feast;
    CREATE SCHEMA IF NOT EXISTS mlgov;
    GRANT ALL ON SCHEMA feast TO $POSTGRES_USER;
    GRANT ALL ON SCHEMA mlgov TO $POSTGRES_USER;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --file /mlgov_ddl.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    SELECT 'CREATE DATABASE mlflow'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')\gexec
SQL
