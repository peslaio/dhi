#!/bin/sh
set -eu

export PATH="/usr/lib/postgresql/15/bin:$PATH"
attempt=0
until pg_isready --host=app --port=5432 --username=postgres >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 90 ]; then
    echo "PostgreSQL did not become ready" >&2
    exit 11
  fi
  sleep 1
done

if ! psql --host=app --port=5432 --username=postgres --dbname=postgres \
  --set=ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS dhi_contract (
  id integer PRIMARY KEY,
  value text NOT NULL
);
INSERT INTO dhi_contract (id, value) VALUES (1, 'postgresql-app-ok')
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;
SQL
then
  echo "PostgreSQL contract write failed" >&2
  exit 10
fi

if ! value="$(psql --host=app --port=5432 --username=postgres --dbname=postgres \
  --tuples-only --no-align --command='SELECT value FROM dhi_contract WHERE id = 1')"; then
  echo "PostgreSQL contract read failed" >&2
  exit 10
fi
if [ "$value" != "postgresql-app-ok" ]; then
  echo "PostgreSQL returned '$value', expected 'postgresql-app-ok'" >&2
  exit 10
fi
printf '%s\n' "$value"
