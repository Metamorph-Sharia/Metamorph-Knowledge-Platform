#!/bin/sh
# BI's own database (its pipeline's private store), beside the platform's: a role and database of its own.
# Runs on a fresh volume; on an older one: docker compose exec postgres sh /docker-entrypoint-initdb.d/02-bi.sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
SELECT 'CREATE ROLE bi LOGIN PASSWORD ''${BI_DB_PASSWORD:-bi-dev}''' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bi')\gexec
SELECT 'CREATE DATABASE bi OWNER bi' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'bi')\gexec
SQL
